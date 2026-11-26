#include "startupwork.h"

#include "Logger.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QFontDatabase>
#include <QSet>
#include <QThread>
#include <QTimer>

#include <memory>

#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif

// How long one turn of adding fonts may hold the window's thread before it handles events again.
static constexpr qint64 kSliceMs = 25;

// letitedit (T383): a worker that only reads files ahead lets everything else read the disk first. On a cold disk (the
// first open after a restart) its reads at normal priority queued in front of the window's own and held the first
// window back for seconds. Windows' background mode gives this thread's disk reads the lowest priority.
static void readInTheBackground()
{
#ifdef Q_OS_WIN
    ::SetThreadPriority(::GetCurrentThread(), THREAD_MODE_BACKGROUND_BEGIN);
#endif
}

StartupWork &StartupWork::instance()
{
    static StartupWork *work = new StartupWork(qApp);
    return *work;
}

StartupWork::StartupWork(QObject *parent)
    : QObject(parent)
{
    connect(qApp, &QCoreApplication::aboutToQuit, this, &StartupWork::stopWorker);
}

StartupWork::~StartupWork()
{
    stopWorker();
}

void StartupWork::stopWorker()
{
    m_stop = true;
    if (m_worker && m_worker->isRunning())
        m_worker->wait();
    for (auto *reader : std::as_const(m_readers))
        reader->wait();
    qDeleteAll(m_readers);
    m_readers.clear();
}

void StartupWork::readAheadFirstOpen(const QString &appDir, const QString &markerPath)
{
    if (qEnvironmentVariableIsSet("LETITEDIT_NO_READAHEAD") || !m_readers.isEmpty())
        return;
    const QFileInfo exe(QCoreApplication::applicationFilePath());
    const QString build = QStringLiteral("%1 %2 %3")
                              .arg(exe.fileName())
                              .arg(exe.size())
                              .arg(exe.lastModified().toMSecsSinceEpoch());
    QFile marker(markerPath);
    if (marker.open(QIODevice::ReadOnly) && QString::fromUtf8(marker.readAll()).trimmed() == build)
        return;
    marker.close();
    // In the order the start-up loads them: the engine's modules (and the plug-ins its frei0r module opens one by one),
    // the libraries beside the program, the engine's presets and profiles, Qt's QML modules, then the editor's own QML.
    struct Group
    {
        QString dir;
        QStringList patterns;
    };
    const QList<Group> groups{
        {QStringLiteral("lib/mlt"), {QStringLiteral("*.dll")}},
        {QStringLiteral("lib/frei0r-1"), {QStringLiteral("*.dll")}},
        {QString(), {QStringLiteral("*.dll")}},
        {QStringLiteral("share/mlt"), {QStringLiteral("*")}},
        {QStringLiteral("lib/qml"),
         {QStringLiteral("*.dll"), QStringLiteral("qmldir"), QStringLiteral("*.qml"), QStringLiteral("*.js"),
          QStringLiteral("*.mjs")}},
        {QStringLiteral("lib/qt6"), {QStringLiteral("*.dll")}},
        {QStringLiteral("share/shotcut/qml"), {QStringLiteral("*.qml"), QStringLiteral("*.js")}},
        {QStringLiteral("lib/ladspa"), {QStringLiteral("*.dll")}},
    };
    // letitedit (T383): libraries the editor itself never opens (the speech model's, which its own program loads, and
    // the software OpenGL fallback), about 200 MB that held up a cold start
    const QStringList skip{QStringLiteral("ggml*.dll"), QStringLiteral("libwhisper*.dll"),
                           QStringLiteral("libopenblas*.dll"), QStringLiteral("opengl32sw.dll")};
    // The first reader lists the files (not the window's thread), then three read them, sharing the list. Until the
    // engine is loaded they read at normal priority, which brings the engine's modules in faster than it loads them one
    // by one; after that, at the lowest disk priority, so the main window's own reads go first (T383).
    static constexpr int kReaders = 3;
    m_readersLeft = kReaders;
    auto files = std::make_shared<QStringList>();
    auto listed = std::make_shared<std::atomic<bool>>(false);
    auto next = std::make_shared<std::atomic<int>>(0);
    auto bytes = std::make_shared<std::atomic<qint64>>(0);
    auto loaded = std::make_shared<std::atomic<int>>(0);
    const qint64 started = QDateTime::currentMSecsSinceEpoch();
    for (int r = 0; r < kReaders; ++r) {
        auto *reader = QThread::create([=]() {
            if (r == 0) {
                for (const auto &group : groups) {
                    const QString dir = group.dir.isEmpty() ? appDir : appDir + QLatin1Char('/') + group.dir;
                    QDirIterator it(dir, group.patterns, QDir::Files,
                                    group.dir.isEmpty() ? QDirIterator::NoIteratorFlags : QDirIterator::Subdirectories);
                    while (it.hasNext() && !m_stop) {
                        const QString path = it.next();
                        if (!QDir::match(skip, it.fileName()))
                            *files << path;
                    }
                }
                LOG_INFO() << "startup: first open of this build, reading" << files->size() << "of its files ahead";
                *listed = true;
            }
            while (!*listed && !m_stop)
                QThread::msleep(10);
            bool background = false;
            QByteArray buffer(1 << 20, Qt::Uninitialized);
            while (!m_stop) {
                waitWhileHeld(m_holdReadAhead);
                if (!background && m_engineLoaded) {
                    readInTheBackground();
                    background = true;
                }
                const int i = next->fetch_add(1);
                if (i >= files->size())
                    break;
                const QString &path = files->at(i);
#ifdef Q_OS_WIN
                // a library this process has open already was read when it was loaded
                if (path.endsWith(QLatin1String(".dll"), Qt::CaseInsensitive)
                    && ::GetModuleHandleW(reinterpret_cast<LPCWSTR>(QFileInfo(path).fileName().utf16()))) {
                    loaded->fetch_add(1);
                    continue;
                }
#endif
                QFile f(path);
                if (f.open(QIODevice::ReadOnly)) {
                    qint64 n;
                    while ((n = f.read(buffer.data(), buffer.size())) > 0 && !m_stop)
                        bytes->fetch_add(n);
                }
            }
            if (m_readersLeft.fetch_sub(1) == 1 && !m_stop) {
                QFile done(markerPath);
                if (done.open(QIODevice::WriteOnly | QIODevice::Truncate))
                    done.write(build.toUtf8());
                LOG_INFO() << "startup: read the build's files ahead in" << QDateTime::currentMSecsSinceEpoch() - started
                           << "ms," << bytes->load() / (1024 * 1024) << "MB;" << loaded->load()
                           << "libraries were open already";
            }
        });
        reader->setObjectName(QStringLiteral("letitedit first-open read-ahead"));
        m_readers << reader;
        reader->start(QThread::LowPriority);
    }
}

void StartupWork::setEngineLoaded()
{
    m_holdFonts = true;
    m_holdReadAhead = true;
    m_engineLoaded = true;
}

void StartupWork::setWindowUp()
{
    m_holdFonts = false;
}

// letitedit (T383): while the main window is made, and then while its filters load, reading ahead only competes with
// them on a cold disk (and every file read is checked by the antivirus, whatever the reader's priority), so the readers
// wait for them
void StartupWork::waitWhileHeld(const std::atomic<bool> &hold) const
{
    while (hold && !m_stop)
        QThread::msleep(20);
}

void StartupWork::loadFonts(const QStringList &dirs)
{
    if (m_worker || m_fontsLoaded)
        return;
    m_dirs = dirs;
    m_startedMs = QDateTime::currentMSecsSinceEpoch();
    // The worker lists the files, hands the list over, then reads each file once (its bytes are dropped) so that the
    // window's thread finds it in the disk cache, already scanned by any antivirus, when it adds it.
    m_worker = QThread::create([this, dirs]() {
        readInTheBackground();
        QStringList files;
        QSet<QString> seen;
        for (const auto &dir : dirs) {
            QDirIterator it(dir.trimmed(),
                            {QStringLiteral("*.ttf"), QStringLiteral("*.otf"), QStringLiteral("*.ttc"),
                             QStringLiteral("*.otc")},
                            QDir::Files,
                            QDirIterator::Subdirectories);
            while (it.hasNext() && !m_stop) {
                const QString path = it.next();
                const QString key = it.fileName().toLower();
                if (seen.contains(key))
                    continue;
                seen.insert(key);
                files << path;
            }
        }
        QMetaObject::invokeMethod(this, [this, files]() {
            m_files = files;
            m_listed = true;
            addSomeFonts();
        }, Qt::QueuedConnection);
        QByteArray buffer(1 << 20, Qt::Uninitialized);
        for (const auto &path : std::as_const(files)) {
            waitWhileHeld(m_holdFonts);
            if (m_stop)
                return;
            QFile f(path);
            if (f.open(QIODevice::ReadOnly)) {
                while (f.read(buffer.data(), buffer.size()) > 0 && !m_stop) {
                }
            }
            m_readAhead.fetch_add(1);
            if (m_mainWaiting.exchange(false))
                QMetaObject::invokeMethod(this, &StartupWork::addSomeFonts, Qt::QueuedConnection);
        }
    });
    m_worker->setObjectName(QStringLiteral("letitedit fonts read-ahead"));
    connect(m_worker, &QThread::finished, m_worker, &QObject::deleteLater);
    connect(m_worker, &QThread::destroyed, this, [this]() { m_worker = nullptr; });
    m_worker->start(QThread::LowPriority);
}

void StartupWork::addSomeFonts()
{
    if (!m_listed || m_fontsLoaded)
        return;
    QElapsedTimer slice;
    slice.start();
    while (m_next < m_files.size()) {
        if (m_next >= m_readAhead.load()) {
            // caught up with the worker: it calls again after its next file (checked twice, so no call is lost)
            m_mainWaiting = true;
            if (m_next >= m_readAhead.load() || !m_mainWaiting.exchange(false))
                return;
        }
        if (slice.elapsed() >= kSliceMs) {
            QTimer::singleShot(0, this, &StartupWork::addSomeFonts);
            return;
        }
        if (QFontDatabase::addApplicationFont(m_files.at(m_next)) >= 0)
            ++m_loaded;
        else
            ++m_failed;
        ++m_next;
    }
    fontsDone();
}

void StartupWork::fontsDone()
{
    m_fontsLoaded = true;
    LOG_INFO() << "letitedit fonts: loaded" << m_loaded << "files," << m_failed << "failed, from" << m_dirs << "in"
               << QDateTime::currentMSecsSinceEpoch() - m_startedMs << "ms, the window answering meanwhile";
    m_files.clear();
    checkReady();
}

void StartupWork::setFiltersLoaded()
{
    if (m_filtersLoaded)
        return;
    m_filtersLoaded = true;
    checkReady();
}

void StartupWork::checkReady()
{
    if (isReady()) {
        m_holdReadAhead = false;
        emit ready();
    }
}

void StartupWork::whenReady(QObject *context, std::function<void()> f)
{
    if (isReady()) {
        f();
        return;
    }
    connect(this, &StartupWork::ready, context, [f]() { f(); }, Qt::SingleShotConnection);
}
