#ifndef LEARNLOOKS_H
#define LEARNLOOKS_H

// "Learn from a video" (Home) and New video's "Match a video I like" (T164): the person shows the AI one to three videos
// they like and it learns a Look and saves it to Your Looks (skills/letitedit-learn). The editor writes a job file, sends the
// request to the chat, and shows the stages the AI reports through bridge/learn_job.py. A New video started before the Look is
// ready waits for it (a pending-video.json beside the job) and is sent by tick() when the Look is saved.

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "letitedit/dialogs/sharelooks.h"
#include "mainwindow.h"
#include "settings.h"
#include <QtWidgets>
#include <algorithm>
#ifdef Q_OS_WIN
#include <windows.h>
#else
#include <csignal>
#endif

namespace LearnLooks {

// is the editor process that started a job still running? (its AI runs as its child, so a closed editor ends the learning)
inline bool processAlive(qint64 pid)
{
    if (pid <= 0)
        return true; // a job from before pids were recorded: nothing to go on
#ifdef Q_OS_WIN
    HANDLE handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, DWORD(pid));
    if (!handle)
        return GetLastError() == ERROR_ACCESS_DENIED;
    DWORD code = 0;
    const bool alive = GetExitCodeProcess(handle, &code) && code == STILL_ACTIVE;
    CloseHandle(handle);
    return alive;
#else
    return ::kill(pid_t(pid), 0) == 0 || errno == EPERM;
#endif
}

inline QString jobsFolder()
{
    const QString own = qEnvironmentVariable("LETITEDIT_LEARN_JOBS");
    if (!own.isEmpty())
        return QDir::cleanPath(own);
    return QDir::cleanPath(QDir(Settings.videoProjectsFolder()).filePath(QStringLiteral("../Learning")));
}

// the usual time, measured once on this PC (tests/t128): about 11 minutes for one reference of under a minute
inline int estimateSeconds(int videos) { return qBound(1, videos, 3) * 12 * 60; }

inline QJsonObject readJob(const QString &path)
{
    QFile file(path);
    return file.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(file.readAll()).object() : QJsonObject();
}

inline bool writeJob(const QString &path, const QJsonObject &job)
{
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly))
        return false;
    file.write(QJsonDocument(job).toJson());
    return file.commit();
}

inline bool running(const QJsonObject &job)
{
    const QString state = job.value(QStringLiteral("state")).toString();
    return state == QLatin1String("queued") || state == QLatin1String("learning");
}

// A learn whose editor is gone can never finish (T167): the AI doing it was that editor's child
inline bool orphaned(const QJsonObject &job)
{
    return running(job) && !processAlive(qint64(job.value(QStringLiteral("pid")).toDouble()));
}

// This editor's own learn whose AI ended its turn without saving or failing it (it may be asking something in the chat)
inline bool stalled(const QJsonObject &job)
{
    if (!running(job) || qint64(job.value(QStringLiteral("pid")).toDouble()) != QCoreApplication::applicationPid())
        return false;
    const qint64 sinceStart = (QDateTime::currentMSecsSinceEpoch() - qint64(job.value(QStringLiteral("started_ms")).toDouble())) / 1000;
    return sinceStart > 90 && !aiChatState().value(QStringLiteral("busy")).toBool();
}

inline void markFailed(const QString &path, QJsonObject job, const QString &message)
{
    job.insert(QStringLiteral("state"), QStringLiteral("failed"));
    job.insert(QStringLiteral("message"), message);
    job.insert(QStringLiteral("finished"), QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
    writeJob(path, job);
}

// The newest job (any state) and the newest one still running (a job left over from a crash stops counting after
// twelve hours, and one whose editor is gone counts as stopped)
inline QString newestJob(bool runningOnly)
{
    QString best;
    QDateTime bestTime;
    for (const auto &entry : QDir(jobsFolder()).entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        const QString path = QDir(entry.absoluteFilePath()).filePath(QStringLiteral("job.json"));
        const QJsonObject job = readJob(path);
        if (job.isEmpty() || (runningOnly && (!running(job) || orphaned(job))))
            continue;
        const QDateTime started = QDateTime::fromMSecsSinceEpoch(qint64(job.value(QStringLiteral("started_ms")).toDouble()));
        if (runningOnly && started.secsTo(QDateTime::currentDateTime()) > 12 * 3600)
            continue;
        if (best.isEmpty() || started > bestTime) {
            best = path;
            bestTime = started;
        }
    }
    return best;
}

inline QString activeJob() { return newestJob(true); }

inline QString minutesWords(qint64 seconds)
{
    const int minutes = int((seconds + 59) / 60);
    return minutes <= 1 ? QObject::tr("about a minute") : QObject::tr("about %1 minutes").arg(minutes);
}

// A job's words as the person reads them: the tools write plain sentences, and a raw error that still gets through (a
// Python traceback, or a file path in a quoted traceback line) is never shown: the fallback is, and the details stay
// behind Details
inline bool rawError(const QString &text)
{
    return text.contains(QLatin1String("Traceback (most recent call last)")) || text.contains(QLatin1String("File \""));
}

inline QString plainMessage(const QString &text, const QString &fallback)
{
    return text.isEmpty() || rawError(text) ? fallback : text;
}

// "Watching it frame by frame - about 8 minutes left" for one job
inline QString progressLine(const QJsonObject &job)
{
    const QString state = job.value(QStringLiteral("state")).toString();
    if (state == QLatin1String("done"))
        return QObject::tr("Saved to Your Looks");
    if (state == QLatin1String("failed"))
        return plainMessage(job.value(QStringLiteral("message")).toString(), QObject::tr("Learning stopped"));
    if (stalled(job))
        return QObject::tr("Your AI has stopped without saving the Look. Look in the chat: it may be asking you something. "
                           "Answer it there, or press Try again.");
    const qint64 elapsed = (QDateTime::currentMSecsSinceEpoch() - qint64(job.value(QStringLiteral("started_ms")).toDouble())) / 1000;
    const qint64 left = job.value(QStringLiteral("estimate_s")).toInt() - elapsed;
    return QObject::tr("%1 - %2").arg(job.value(QStringLiteral("message")).toString(QObject::tr("Getting ready")),
                                      left > 0 ? QObject::tr("%1 left (an estimate)").arg(minutesWords(left))
                                               : QObject::tr("taking longer than usual, still working"));
}

// a link to a video (YouTube, TikTok, Instagram, Vimeo...) rather than a file on this PC (T176)
inline bool isLink(const QString &text)
{
    const QUrl url(text.trimmed(), QUrl::StrictMode);
    return url.isValid() && (url.scheme() == QLatin1String("https") || url.scheme() == QLatin1String("http")) && !url.host().isEmpty();
}

// T189: the AI names the Look in the request (the person can rename it from its card later)
inline QString naming()
{
    return QStringLiteral("Name it yourself (I don't name it): its title is a short plain name, two to five words, that says what "
                          "it looks like, such as \"Bold words over cutaways\", general enough to reuse and never the reference's "
                          "creator, channel, show or subject; its line is one sentence a newcomer to editing understands. ");
}

// Where the person's own Looks are kept: Documents\letitedit\My Looks for the main window, the profile's own for a test window
inline QString myLooksFolder()
{
    return qEnvironmentVariable("LETITEDIT_MY_LOOKS",
                                qEnvironmentVariable("LETITEDIT_INSTANCE", "main") == QLatin1String("main")
                                    ? QDir(QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation))
                                          .filePath(QStringLiteral("letitedit/My Looks"))
                                    : QDir(Settings.appDataLocation()).filePath(QStringLiteral("My Looks")));
}

// T189: rename one of the person's own Looks from its card: asks for the new name and saves it with the Look
// (bridge/learned_looks.py rename: a new revision with only the name changed). True when it was renamed.
inline bool renameLook(QWidget *parent, const QString &id, const QString &current)
{
    QInputDialog ask(parent);
    ask.setObjectName(QStringLiteral("learnRenameDialog"));
    ask.setWindowTitle(QObject::tr("Rename this Look"));
    ask.setLabelText(QObject::tr("New name for this Look:"));
    ask.setTextValue(current);
    QTimer::singleShot(0, &ask, [&ask]() { // its text box, named for tests and screen readers once it is shown
        if (auto field = ask.findChild<QLineEdit *>())
            field->setObjectName(QStringLiteral("learnRenameText"));
    });
    const bool ok = ask.exec() == QDialog::Accepted;
    const QString wanted = ask.textValue().simplified().left(60);
    if (!ok || wanted.isEmpty() || wanted == current)
        return false;
    QProcess process;
    process.start(aiChatSettings().value(QStringLiteral("python")).toString(),
                  {aiRootPath(QStringLiteral("bridge/learned_looks.py")), QStringLiteral("rename"), id, wanted, QStringLiteral("--root"),
                   QDir::toNativeSeparators(myLooksFolder())});
    const bool finished = process.waitForFinished(30000);
    const QByteArray out = process.readAllStandardOutput();
    const QJsonObject reply = QJsonDocument::fromJson(out.mid(out.lastIndexOf('{'))).object();
    if (!finished || !reply.value(QStringLiteral("ok")).toBool()) {
        if (!finished)
            process.kill();
        QMessageBox::warning(parent, QObject::tr("Rename this Look"),
                             QObject::tr("Couldn't rename it: %1").arg(reply.value(QStringLiteral("error")).toString(QObject::tr("it took too long"))));
        return false;
    }
    return true;
}

inline QString requestText(const QString &jobPath, const QStringList &files, const QString &note)
{
    QStringList native, links;
    for (const QString &file : files)
        (isLink(file) ? links : native) << (isLink(file) ? file.trimmed() : QDir::toNativeSeparators(file));
    if (!links.isEmpty()) {
        // the link is fetched first, by letitedit's own tool (no shell, no web tool, no prompt); the file stays in the
        // person's own folders (never the library, never shipped), and the stage shows as "Getting the video"
        QString text = QStringLiteral("Learn a Look from the video%1 I chose: %2.\n\nUse the `letitedit-learn` skill. Save the Look to my "
                                      "Looks (it is mine; never copy the reference's pictures, sound or words). %3"
                                      "Do not make a video now.\n")
                           .arg(files.size() == 1 ? QString() : QStringLiteral("s"), (native + links).join(QStringLiteral("; ")), naming());
        text += QStringLiteral("\nI gave %1 as a link. Fetch %2 first with letitedit's own tool, before anything else: "
                               "letitedit_fetch(action='reference', url='<the link>') for each link (it runs inside letitedit; don't use a "
                               "shell or web download). Use the `path` it returns as the reference file. The fetched video is private: it stays in "
                               "my own folders where the tool puts it, never in the library or anything shipped. If a video is too long to "
                               "fetch whole, fetch the parts to learn from yourself with start and end, as letitedit-learn says, without "
                               "asking me. If a fetch fails for another reason, tell me its `error` in plain words.\n")
                    .arg(links.size() == 1 ? QStringLiteral("this video") : QStringLiteral("%1 videos").arg(links.size()),
                         links.size() == 1 ? QStringLiteral("it") : QStringLiteral("them"));
        if (!note.trimmed().isEmpty())
            text += QStringLiteral("What I like about it: %1\n").arg(note.trimmed());
        text += QStringLiteral("\nThe editor shows my progress from a small file. Report each stage as you reach it, from your shell:\n"
                               "python \"%1\" progress \"%2\" <stage> [a few words]\n"
                               "with <stage> one of: fetch (getting the video from its link), measure (the importer measuring the video), "
                               "look (you watching it frame by frame), write (writing the recipe), save (saving it). When the Look is saved, run:\n"
                               "python \"%1\" done \"%2\" <the saved Look's id>\n"
                               "and if you cannot finish: python \"%1\" fail \"%2\" \"<why, in a few plain words>\".")
                    .arg(QDir::toNativeSeparators(aiRootPath(QStringLiteral("bridge/learn_job.py"))), QDir::toNativeSeparators(jobPath));
        return text;
    }
    QString text = QStringLiteral("Learn a Look from the video%1 I chose: %2.\n\nUse the `letitedit-learn` skill. Save the Look to my "
                                  "Looks (it is mine; never copy the reference's pictures, sound or words). %3"
                                  "Do not make a video now.\n")
                       .arg(files.size() == 1 ? QString() : QStringLiteral("s"), native.join(QStringLiteral("; ")), naming());
    if (!note.trimmed().isEmpty())
        text += QStringLiteral("What I like about it: %1\n").arg(note.trimmed());
    text += QStringLiteral("\nThe editor shows my progress from a small file. Report each stage as you reach it, from your shell:\n"
                           "python \"%1\" progress \"%2\" <stage> [a few words]\n"
                           "with <stage> one of: measure (the importer measuring the video), look (you watching it frame by frame), "
                           "write (writing the recipe), save (saving it). When the Look is saved, run:\n"
                           "python \"%1\" done \"%2\" <the saved Look's id>\n"
                           "and if you cannot finish: python \"%1\" fail \"%2\" \"<why, in a few plain words>\".")
                .arg(QDir::toNativeSeparators(aiRootPath(QStringLiteral("bridge/learn_job.py"))), QDir::toNativeSeparators(jobPath));
    return text;
}

// T202: the finished videos of a project, newest first: the videos beside it named after it, its previews, roughs and
// assemblies left out (as bridge/project_look.py versions does)
inline QFileInfoList finishedVideos(const QString &project)
{
    const QFileInfo file(project);
    if (project.isEmpty() || file.suffix().compare(QLatin1String("mlt"), Qt::CaseInsensitive) != 0)
        return {};
    static const QRegularExpression notFinal(QStringLiteral("(?:^|[\\s_-])(preview|rough|assembly|excerpt|clip|test)(?:$|[\\s_.-])"),
                                             QRegularExpression::CaseInsensitiveOption);
    const QString stem = file.completeBaseName();
    // a project beside it whose name starts with this one's ("Trip v2" beside "Trip") owns the videos named after it
    QStringList longer;
    for (const QFileInfo &other : file.dir().entryInfoList({QStringLiteral("*.mlt")}, QDir::Files))
        if (other.completeBaseName().size() > stem.size() && other.completeBaseName().startsWith(stem))
            longer << other.completeBaseName();
    QFileInfoList out;
    for (const QFileInfo &video : file.dir().entryInfoList({QStringLiteral("*.mp4"), QStringLiteral("*.mov"), QStringLiteral("*.mkv"),
                                                            QStringLiteral("*.webm")},
                                                           QDir::Files, QDir::Time)) {
        const QString name = video.completeBaseName();
        if (!name.startsWith(stem) || notFinal.match(name.mid(stem.size())).hasMatch())
            continue;
        if (std::none_of(longer.cbegin(), longer.cend(), [&name](const QString &other) { return name.startsWith(other); }))
            out << video;
    }
    return out;
}

// T202: the request for "Make a Look from this video": a finished video of a letitedit project, learned from its exact
// timeline (letitedit-learn, "From a finished project"). An empty video means the project has no export yet: the person
// chose "Export it and make the Look", so the AI exports it first.
inline QString projectRequestText(const QString &jobPath, const QString &project, const QString &video)
{
    const QString nativeProject = QDir::toNativeSeparators(project);
    QString text = video.isEmpty()
                       ? QStringLiteral("Make a Look from my video %1. It has no exported video yet: export it first as it stands "
                                        "(letitedit_export), wait for it, then make the Look from that export.\n\n")
                             .arg(nativeProject)
                       : QStringLiteral("Make a Look from my finished video %1 (its project: %2).\n\n")
                             .arg(QDir::toNativeSeparators(video), nativeProject);
    text += QStringLiteral("Use the `letitedit-learn` skill, its part \"From a finished project\": start with "
                           "letitedit_learn(action='project', reference='%1', result='%2', out=<a new private folder>). Save the "
                           "Look to my Looks (it is mine; never copy the video's pictures, sound or words). %3Do not make a video now.\n")
                .arg(nativeProject, video.isEmpty() ? QStringLiteral("<the export>") : QDir::toNativeSeparators(video), naming());
    text += QStringLiteral("\nThe editor shows my progress from a small file. Report each stage as you reach it, from your shell:\n"
                           "python \"%1\" progress \"%2\" <stage> [a few words]\n"
                           "with <stage> one of: measure (the importer measuring the video), look (you watching it frame by frame), "
                           "write (writing the recipe), save (saving it). When the Look is saved, run:\n"
                           "python \"%1\" done \"%2\" <the saved Look's id>\n"
                           "and if you cannot finish: python \"%1\" fail \"%2\" \"<why, in a few plain words>\".")
                .arg(QDir::toNativeSeparators(aiRootPath(QStringLiteral("bridge/learn_job.py"))), QDir::toNativeSeparators(jobPath));
    return text;
}

// T202: sends "Make a Look from this video" for one finished video (empty: export first) and keeps its progress file,
// so Home shows it like any Learn. True when the AI took it.
inline bool startFromProject(MainWindow *window, const QString &project, const QString &video, QWidget *parent)
{
    const QString heading = QObject::tr("Make a Look from this video");
    if (aiChatState().value(QStringLiteral("busy")).toBool()) {
        QMessageBox::information(parent, heading,
                                 QObject::tr("Your AI is still answering the last request. Wait for it to finish (or press Stop in the "
                                             "chat), then try again."));
        return false;
    }
    const QString id = QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd-hhmmsszzz"));
    const QString directory = QDir(jobsFolder()).filePath(id);
    const QString path = QDir(directory).filePath(QStringLiteral("job.json"));
    const QJsonObject job{{QStringLiteral("id"), id},
                          {QStringLiteral("name"), QString()},
                          {QStringLiteral("my_looks"), myLooksFolder()},
                          {QStringLiteral("note"), QString()},
                          {QStringLiteral("files"), QJsonArray::fromStringList(video.isEmpty() ? QStringList() : QStringList{video})},
                          {QStringLiteral("links"), QJsonArray()},
                          {QStringLiteral("project"), project},
                          {QStringLiteral("state"), QStringLiteral("queued")},
                          {QStringLiteral("stage_index"), 0},
                          {QStringLiteral("message"), QObject::tr("Getting ready")},
                          {QStringLiteral("started_ms"), double(QDateTime::currentMSecsSinceEpoch())},
                          {QStringLiteral("estimate_s"), estimateSeconds(1)},
                          {QStringLiteral("pid"), double(QCoreApplication::applicationPid())}};
    if (!QDir().mkpath(directory) || !writeJob(path, job)) {
        QMessageBox::warning(parent, heading, QObject::tr("Couldn't make a folder to keep the progress in."));
        return false;
    }
    const QString name = QFileInfo(video.isEmpty() ? project : video).completeBaseName();
    window->setProperty("letitedit:learnJob", path);
    const bool accepted = aiChatRequest(window, projectRequestText(path, project, video),
                                        QObject::tr("Make a Look from “%1”").arg(name), false, true);
    window->setProperty("letitedit:learnJob", QVariant());
    if (!accepted) {
        QDir(directory).removeRecursively();
        const QString why = aiChatRefusal();
        QMessageBox::warning(parent, heading,
                             !why.isEmpty() ? why : QObject::tr("Your AI couldn't take the request just now. Try again in a moment."));
        return false;
    }
    window->showStatusMessage(QObject::tr("Your AI is making a Look from “%1”. It appears under Your Looks when it's done; your AI "
                                          "names it and you can rename it from its card.")
                                  .arg(name),
                              15);
    return true;
}

// T202: "Make a Look from this video" for a project with no video picked: its newest finished video, or (none yet) the
// offer to export it first
inline bool offerFromProject(MainWindow *window, const QString &project, QWidget *parent)
{
    const QFileInfoList videos = finishedVideos(project);
    if (!videos.isEmpty())
        return startFromProject(window, project, videos.first().absoluteFilePath(), parent);
    QMessageBox ask(QMessageBox::Question, QObject::tr("Make a Look from this video"),
                    QObject::tr("This video hasn't been exported yet. A Look is made from the finished video, so it needs exporting first."),
                    QMessageBox::Cancel, parent);
    ask.setObjectName(QStringLiteral("lookFromVideoExportFirst"));
    auto *go = ask.addButton(QObject::tr("Export it and make the Look"), QMessageBox::AcceptRole);
    ask.exec();
    return ask.clickedButton() == go && startFromProject(window, project, QString(), parent);
}

// Sends New videos that waited for their Look. Called by the home page's timer; nothing else to start.
inline void tick(MainWindow *window)
{
    if (!window)
        return;
    const bool busy = aiChatState().value(QStringLiteral("busy")).toBool();
    static QHash<QString, int> idleTicks; // ticks a running job has seen the AI idle (it ended its turn without done or fail)
    for (const auto &entry : QDir(jobsFolder()).entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        const QDir directory(entry.absoluteFilePath());
        const QString jobPath = directory.filePath(QStringLiteral("job.json"));
        QJsonObject job = readJob(jobPath);
        if (job.isEmpty())
            continue;
        // a learn that can't finish any more is marked as stopped, so nothing waits for it for ever (T167): its editor was
        // closed (the AI ran as that editor's child), or the AI has been idle for ten minutes without saving or failing it
        if (orphaned(job)) {
            markFailed(jobPath, job, QObject::tr("letitedit was closed while it was learning. Start it again."));
            job = readJob(jobPath);
        } else if (running(job) && qint64(job.value(QStringLiteral("pid")).toDouble()) == QCoreApplication::applicationPid()) {
            int &idle = idleTicks[jobPath];
            idle = busy ? 0 : idle + 1;
            if (idle >= 300) {
                markFailed(jobPath, job, QObject::tr("Your AI stopped without saving the Look. Look in the chat for why, then start it again."));
                job = readJob(jobPath);
            }
        }
        const QString pendingPath = directory.filePath(QStringLiteral("pending-video.json"));
        if (!QFileInfo::exists(pendingPath))
            continue;
        if (running(job) || busy)
            continue;
        const QJsonObject pending = readJob(pendingPath);
        QString request = pending.value(QStringLiteral("request")).toString();
        const bool saved = job.value(QStringLiteral("state")).toString() == QLatin1String("done")
                           && !job.value(QStringLiteral("look_id")).toString().isEmpty();
        if (!saved) {
            // the sentence written for a chosen Look would send the AI to read a Look called "auto"
            request.replace(QRegularExpression(QStringLiteral("\\(I chose the Style \"([^\"]*)\" and its Look \"@@LOOK_NAME@@\"[^\n]*\\)\n")),
                            QStringLiteral("(I chose the Style \"\\1\" and asked you to learn its Look from a video of mine, but that didn't finish: "
                                           "choose one of the Style's Looks for this footage with letitedit_looks(action: \"list\"), from each one's "
                                           "\"needs\" line, and tell me which you chose and why before you start.)\n"));
            request.remove(QRegularExpression(QStringLiteral("\nLook: @@LOOK_NAME@@ \\(@@LOOK_ID@@\\)\n")));
        }
        request.replace(QStringLiteral("@@LOOK_ID@@"), saved ? job.value(QStringLiteral("look_id")).toString() : QStringLiteral("auto"));
        request.replace(QStringLiteral("@@LOOK_NAME@@"), saved ? job.value(QStringLiteral("name")).toString() : QStringLiteral("Let the AI pick"));
        if (!saved)
            request += QStringLiteral("\n(The Look I asked you to learn from my video didn't finish. Choose a fitting Look yourself and tell me which.)\n");
        window->setProperty("letitedit:newVideoFolder", pending.value(QStringLiteral("folder")).toString());
        QString summary = pending.value(QStringLiteral("summary")).toString();
        summary.replace(QStringLiteral("@@LOOK_ID@@"), saved ? job.value(QStringLiteral("look_id")).toString() : QStringLiteral("auto"));
        summary.replace(QStringLiteral("@@LOOK_NAME@@"), saved ? job.value(QStringLiteral("name")).toString() : QStringLiteral("Let the AI pick"));
        if (aiChatRequest(window, request, summary, false, true)) {
            QFile::remove(pendingPath);
            window->setProperty("letitedit:firstCutSent", QDateTime::currentDateTime());
            window->showStatusMessage(saved ? QObject::tr("Your Look is ready, so your AI is making the video now. Follow along in the chat.")
                                            : QObject::tr("The Look didn't finish learning, so your AI is making the video with a Look of its own "
                                                          "choice. Follow along in the chat."), 15);
        }
    }
}

// The panel: pick the videos, say what you like (optional), start; then the stages with the time so far and an estimate.
class Panel : public QWidget
{
public:
    explicit Panel(MainWindow *window, QWidget *parent)
        : QWidget(parent)
        , m_window(window)
    {
        setObjectName(QStringLiteral("learnPanel"));
        auto outer = new QVBoxLayout(this);
        outer->setContentsMargins(0, 0, 0, 0);
        m_stack = new QStackedWidget(this);
        outer->addWidget(m_stack);

        buildChoices();

        buildProgress();

        m_timer = new QTimer(this);
        m_timer->setInterval(1000);
        connect(m_timer, &QTimer::timeout, this, [this]() { refresh(); });
        m_timer->start();
        // a job still running (the window was closed and opened again): show it
        const QString active = activeJob();
        if (!active.isEmpty())
            adopt(active);
    }

    // called with the saved Look's id and the name given to it, once it is saved
    void onLearned(std::function<void(const QString &, const QString &)> action) { m_onLearned = std::move(action); }
    void onStarted(std::function<void(const QString &, const QString &)> action) { m_onStarted = std::move(action); }
    QString jobPath() const { return m_job; }
    bool isLearning() const { return !m_job.isEmpty() && running(readJob(m_job)); }

    void adopt(const QString &path)
    {
        m_job = path;
        m_announced = false;
        m_stack->setCurrentIndex(1);
        refresh();
    }

    // a link joins the list like a file (three at most); the learning fetches it
    void addLink(const QString &text)
    {
        const QString link = text.trimmed();
        if (!isLink(link)) {
            m_problem->setText(tr("That doesn't look like a link to a video. Copy the address from your browser's address bar or the app's Share button."));
            m_problem->show();
            return;
        }
        if (m_files->count() >= 3 || !m_files->findItems(link, Qt::MatchExactly).isEmpty())
            return;
        auto item = new QListWidgetItem(link, m_files);
        item->setToolTip(tr("Fetched by your AI when the learning starts"));
        m_link->clear();
        changed();
    }

    void addFiles(const QStringList &paths)
    {
        for (const QString &path : paths) {
            const QString native = QDir::toNativeSeparators(path);
            if (m_files->count() >= 3 || !QFileInfo(path).isFile() || !m_files->findItems(native, Qt::MatchExactly).isEmpty())
                continue;
            m_files->addItem(native);
        }
        changed();
    }

private:
    void buildChoices()
    {
        // 0: choose
        auto choose = new QWidget(this);
        auto column = new QVBoxLayout(choose);
        column->setContentsMargins(0, 0, 0, 0);
        column->setSpacing(6);
        auto lead = new QLabel(tr("Show it one to three videos you like, as files or links. It studies the cuts, captions, b-roll and sound, and saves "
                                  "the way they are made as a Look of your own. Your videos are only read, never changed."),
                               choose);
        lead->setObjectName(QStringLiteral("learnLead"));
        lead->setWordWrap(true);
        column->addWidget(lead);
        m_files = new QListWidget(choose);
        m_files->setObjectName(QStringLiteral("learnFiles"));
        m_files->setFixedHeight(76);
        m_files->setSelectionMode(QAbstractItemView::ExtendedSelection);
        column->addWidget(m_files);
        auto fileRow = new QHBoxLayout;
        auto add = new QPushButton(tr("Add videos..."), choose);
        add->setObjectName(QStringLiteral("learnAdd"));
        add->setAutoDefault(false);
        connect(add, &QPushButton::clicked, this, [this]() {
            const QStringList picked = QFileDialog::getOpenFileNames(
                this, tr("Choose videos you like"), Settings.openPath(),
                tr("Videos (*.mp4 *.mov *.m4v *.mkv *.avi *.mts *.webm *.mxf);;All files (*)"));
            addFiles(picked);
        });
        fileRow->addWidget(add);
        auto remove = new QPushButton(tr("Remove"), choose);
        remove->setObjectName(QStringLiteral("learnRemove"));
        remove->setAutoDefault(false);
        connect(remove, &QPushButton::clicked, this, [this]() {
            for (auto item : m_files->selectedItems())
                delete item;
            changed();
        });
        fileRow->addWidget(remove);
        // for tests and screen readers: paths set here (semicolon separated) are added, as if chosen
        auto paste = new QLineEdit(choose);
        paste->setObjectName(QStringLiteral("learnPaste"));
        paste->setFixedSize(1, 1);
        paste->setStyleSheet(QStringLiteral("color: transparent; background: transparent; border: none;"));
        connect(paste, &QLineEdit::textChanged, this, [this, paste](const QString &text) {
            if (text.isEmpty())
                return;
            addFiles(text.split(QLatin1Char(';'), Qt::SkipEmptyParts));
            paste->clear();
        });
        fileRow->addWidget(paste);
        fileRow->addStretch(1);
        column->addLayout(fileRow);
        // or a link (T176): the AI fetches it with letitedit's own tool when the learning starts
        auto linkRow = new QHBoxLayout;
        linkRow->setSpacing(6);
        m_link = new QLineEdit(choose);
        m_link->setObjectName(QStringLiteral("learnLink"));
        m_link->setAccessibleName(tr("Link to a video"));
        m_link->setPlaceholderText(tr("Or paste a link: YouTube, TikTok, Instagram, Vimeo..."));
        m_link->setClearButtonEnabled(true);
        m_link->setToolTip(tr("Paste the address of a video you like. Your AI fetches it when the learning starts and keeps it "
                              "private, in your own folders."));
        linkRow->addWidget(m_link, 1);
        m_addLink = new QPushButton(tr("Add link"), choose);
        m_addLink->setObjectName(QStringLiteral("learnAddLink"));
        m_addLink->setAutoDefault(false);
        m_addLink->setEnabled(false);
        linkRow->addWidget(m_addLink);
        column->addLayout(linkRow);
        connect(m_link, &QLineEdit::textChanged, this, [this](const QString &text) {
            m_addLink->setEnabled(isLink(text) && m_files->count() < 3);
        });
        connect(m_addLink, &QPushButton::clicked, this, [this]() { addLink(m_link->text()); });
        connect(m_link, &QLineEdit::returnPressed, this, [this]() { addLink(m_link->text()); });
        // T189: no name to type: the AI names the Look, and the person can rename it from its card later
        column->addWidget(new QLabel(tr("What do you like about it? (optional)"), choose));
        m_note = new QPlainTextEdit(choose);
        m_note->setObjectName(QStringLiteral("learnNote"));
        m_note->setFixedHeight(54);
        column->addWidget(m_note);
        m_problem = new QLabel(choose);
        m_problem->setObjectName(QStringLiteral("learnProblem"));
        m_problem->setWordWrap(true);
        m_problem->setStyleSheet(QStringLiteral("color: #ff8a80;"));
        m_problem->hide();
        column->addWidget(m_problem);
        m_start = new QPushButton(tr("Learn this Look"), choose);
        m_start->setObjectName(QStringLiteral("learnStart"));
        m_start->setProperty("studioPrimary", true);
        m_start->setAutoDefault(false);
        m_start->setEnabled(false);
        connect(m_start, &QPushButton::clicked, this, [this]() { start(); });
        column->addWidget(m_start, 0, Qt::AlignLeft);
        // T190: what is shared with letitedit when the Look is saved, once and small, with a way to the setting
        auto shareLine = new QLabel(ShareLooks::learnLine(), choose);
        shareLine->setObjectName(QStringLiteral("learnShareLine"));
        shareLine->setWordWrap(true);
        shareLine->setProperty("studioMuted", true);
        shareLine->setStyleSheet(QStringLiteral("font-size: 11px;"));
        shareLine->setTextFormat(Qt::RichText);
        connect(shareLine, &QLabel::linkActivated, this, [this, shareLine](const QString &) {
            ShareLooks::showDialog(this);
            shareLine->setText(ShareLooks::learnLine());
        });
        column->addWidget(shareLine);
        m_stack->addWidget(choose);
    }

    void buildProgress()
    {
        // 1: learning, done or stopped
        auto running = new QWidget(this);
        auto runningColumn = new QVBoxLayout(running);
        runningColumn->setContentsMargins(0, 0, 0, 0);
        runningColumn->setSpacing(6);
        m_title = new QLabel(running);
        m_title->setObjectName(QStringLiteral("learnTitle"));
        m_title->setStyleSheet(QStringLiteral("font-size: 15px; font-weight: 700;"));
        m_title->setWordWrap(true);
        runningColumn->addWidget(m_title);
        m_bar = new QProgressBar(running);
        m_bar->setObjectName(QStringLiteral("learnBar"));
        m_bar->setRange(0, 100);
        m_bar->setTextVisible(false);
        m_bar->setFixedHeight(8);
        runningColumn->addWidget(m_bar);
        m_stage = new QLabel(running);
        m_stage->setObjectName(QStringLiteral("learnStage"));
        m_stage->setWordWrap(true);
        runningColumn->addWidget(m_stage);
        m_steps = new QLabel(running);
        m_steps->setObjectName(QStringLiteral("learnSteps"));
        m_steps->setTextFormat(Qt::RichText);
        m_steps->setProperty("studioMuted", true);
        runningColumn->addWidget(m_steps);
        m_keepGoing = new QLabel(running);
        m_keepGoing->setObjectName(QStringLiteral("learnKeepGoing"));
        m_keepGoing->setWordWrap(true);
        m_keepGoing->setProperty("studioMuted", true);
        runningColumn->addWidget(m_keepGoing);
        // what wasn't learned, in technical words and where the full errors are kept: behind Details
        m_detailsButton = new QToolButton(running);
        m_detailsButton->setObjectName(QStringLiteral("learnDetailsButton"));
        m_detailsButton->setText(tr("Details"));
        m_detailsButton->setCheckable(true);
        m_detailsButton->setAutoRaise(true);
        m_detailsButton->hide();
        runningColumn->addWidget(m_detailsButton, 0, Qt::AlignLeft);
        m_details = new QLabel(running);
        m_details->setObjectName(QStringLiteral("learnDetails"));
        m_details->setWordWrap(true);
        m_details->setTextFormat(Qt::PlainText);
        m_details->setTextInteractionFlags(Qt::TextSelectableByMouse);
        m_details->setProperty("studioMuted", true);
        m_details->setStyleSheet(QStringLiteral("font-size: 11px;"));
        m_details->hide();
        runningColumn->addWidget(m_details);
        connect(m_detailsButton, &QToolButton::toggled, this, [this](bool open) {
            m_details->setVisible(open);
            m_detailsButton->setText(open ? tr("Hide details") : tr("Details"));
        });
        m_again = new QPushButton(tr("Try again"), running);
        m_again->setObjectName(QStringLiteral("learnTryAgain"));
        m_again->setAutoDefault(false);
        connect(m_again, &QPushButton::clicked, this, [this]() { m_job.clear(); m_stack->setCurrentIndex(0); });
        m_again->hide();
        runningColumn->addWidget(m_again, 0, Qt::AlignLeft);
        runningColumn->addStretch(1);
        m_stack->addWidget(running);
    }

    QStringList files() const
    {
        QStringList list;
        for (int i = 0; i < m_files->count(); ++i)
            list << m_files->item(i)->text();
        return list;
    }

    QStringList links() const
    {
        QStringList list;
        for (const QString &entry : files())
            if (isLink(entry))
                list << entry;
        return list;
    }

    void changed()
    {
        m_start->setEnabled(m_files->count() > 0);
        if (m_addLink)
            m_addLink->setEnabled(isLink(m_link->text()) && m_files->count() < 3);
        m_problem->hide();
    }

    void start()
    {
        if (aiChatState().value(QStringLiteral("busy")).toBool()) {
            m_problem->setText(tr("Your AI is still answering the last request. Wait for it to finish (or press Stop in the chat), then press "
                                  "Learn this Look again. Everything here stays filled in."));
            m_problem->show();
            return;
        }
        const QString id = QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd-hhmmsszzz"));
        const QString directory = QDir(jobsFolder()).filePath(id);
        if (!QDir().mkpath(directory)) {
            m_problem->setText(tr("Couldn't make a folder to keep the progress in."));
            m_problem->show();
            return;
        }
        const QString path = QDir(directory).filePath(QStringLiteral("job.json"));
        const QString name = tr("Your new Look"); // shown until the AI has named it (learn_job.py done writes its name)
        QJsonObject job{{QStringLiteral("id"), id},
                        {QStringLiteral("name"), QString()},
                        {QStringLiteral("my_looks"), myLooksFolder()},
                        {QStringLiteral("note"), m_note->toPlainText().trimmed()},
                        {QStringLiteral("files"), QJsonArray::fromStringList(files())},
                        {QStringLiteral("links"), QJsonArray::fromStringList(links())},
                        {QStringLiteral("state"), QStringLiteral("queued")},
                        {QStringLiteral("stage_index"), 0},
                        {QStringLiteral("message"), tr("Getting ready")},
                        {QStringLiteral("started_ms"), double(QDateTime::currentMSecsSinceEpoch())},
                        {QStringLiteral("estimate_s"), estimateSeconds(m_files->count())},
                        {QStringLiteral("pid"), double(QCoreApplication::applicationPid())}};
        if (!writeJob(path, job)) {
            m_problem->setText(tr("Couldn't keep the progress file."));
            m_problem->show();
            return;
        }
        const QString summary = tr("Learn a Look from %1").arg(files().size() == 1 ? tr("a video") : tr("%1 videos").arg(files().size()));
        m_window->setProperty("letitedit:learnJob", path);
        const bool accepted = aiChatRequest(m_window, requestText(path, files(), m_note->toPlainText()), summary, false, true);
        m_window->setProperty("letitedit:learnJob", QVariant());
        if (!accepted) {
            QDir(directory).removeRecursively();
            const QString why = aiChatRefusal();
            m_problem->setText(!why.isEmpty() ? why : tr("Your AI couldn't take the request just now. Press Learn this Look again in a moment."));
            m_problem->show();
            return;
        }
        adopt(path);
        if (m_onStarted)
            m_onStarted(path, name);
    }

    void refresh()
    {
        if (m_job.isEmpty())
            return;
        const QJsonObject job = readJob(m_job);
        if (job.isEmpty())
            return;
        const QString state = job.value(QStringLiteral("state")).toString();
        const QString named = job.value(QStringLiteral("name")).toString();
        m_title->setText(state == QLatin1String("done") ? (named.isEmpty() ? tr("Learned your new Look") : tr("Learned “%1”").arg(named))
                         : named.isEmpty()              ? tr("Learning your new Look")
                                                        : tr("Learning “%1”").arg(named));
        // a job with a link shows "Get the video" as its own first stage (T176); the index follows the stage's name
        const bool fetching = !job.value(QStringLiteral("links")).toArray().isEmpty();
        QStringList keys{QStringLiteral("measure"), QStringLiteral("look"), QStringLiteral("write"), QStringLiteral("save")};
        QStringList names{tr("Measure the video"), tr("Watch it frame by frame"), tr("Write the Look"), tr("Save it")};
        if (fetching) {
            keys.prepend(QStringLiteral("fetch"));
            names.prepend(tr("Get the video"));
        }
        const int stages = keys.size();
        const QString stageKey = job.value(QStringLiteral("stage")).toString();
        const int index = state == QLatin1String("done") ? stages
                          : keys.contains(stageKey)       ? keys.indexOf(stageKey)
                          : stageKey.isEmpty()            ? 0
                                                          : qBound(0, job.value(QStringLiteral("stage_index")).toInt() + (fetching ? 1 : 0), stages - 1);
        m_bar->setValue(state == QLatin1String("done") ? 100 : index * 100 / stages + (state == QLatin1String("learning") ? 10 : 0));
        const bool stalled = LearnLooks::stalled(job); // the AI ended its turn without saving or failing it: Try again is offered
        m_stage->setText(progressLine(job));
        QStringList rows;
        for (int i = 0; i < stages; ++i)
            rows << QStringLiteral("%1 %2").arg(i < index ? QStringLiteral("&#10003;") : i == index && state != QLatin1String("done") ? QStringLiteral("&#9679;") : QStringLiteral("&#9675;"), names[i].toHtmlEscaped());
        m_steps->setText(rows.join(QStringLiteral("<br>")));
        const bool failed = state == QLatin1String("failed");
        QStringList details;
        for (const auto &line : job.value(QStringLiteral("details")).toArray())
            if (!line.toString().trimmed().isEmpty())
                details << line.toString().trimmed();
        const bool showDetails = state == QLatin1String("done") && !details.isEmpty();
        m_details->setText(details.join(QStringLiteral("\n\n")));
        m_detailsButton->setVisible(showDetails);
        if (!showDetails)
            m_detailsButton->setChecked(false);
        m_details->setVisible(showDetails && m_detailsButton->isChecked());
        m_keepGoing->setText(state == QLatin1String("done")
                                 ? (job.value(QStringLiteral("limitations")).toArray().isEmpty()
                                        ? tr("It is saved under Your Looks. Your AI named it; you can rename it from its card.")
                                        : plainMessage(job.value(QStringLiteral("message")).toString(),
                                                       tr("It is saved under Your Looks, but part of it wasn't learned. "
                                                          "You can learn it again to try once more.")))
                                 : failed ? tr("Nothing was saved. You can try again.")
                                          : tr("You can keep going: it will appear under Your Looks when it's done. The usual time is a guess from a "
                                               "first measurement on this PC, and it varies."));
        m_again->setVisible(failed || stalled);
        if (state == QLatin1String("done") && !m_announced) {
            m_announced = true;
            if (m_onLearned)
                m_onLearned(job.value(QStringLiteral("look_id")).toString(), job.value(QStringLiteral("name")).toString());
        }
    }

    MainWindow *m_window;
    QStackedWidget *m_stack = nullptr;
    QListWidget *m_files = nullptr;
    QLineEdit *m_link = nullptr;
    QPushButton *m_addLink = nullptr;
    QPlainTextEdit *m_note = nullptr;
    QLabel *m_problem = nullptr;
    QPushButton *m_start = nullptr;
    QLabel *m_title = nullptr;
    QProgressBar *m_bar = nullptr;
    QLabel *m_stage = nullptr;
    QLabel *m_steps = nullptr;
    QLabel *m_keepGoing = nullptr;
    QToolButton *m_detailsButton = nullptr;
    QLabel *m_details = nullptr;
    QPushButton *m_again = nullptr;
    QTimer *m_timer = nullptr;
    QString m_job;
    bool m_announced = false;
    std::function<void(const QString &, const QString &)> m_onLearned;
    std::function<void(const QString &, const QString &)> m_onStarted;
};

// Home's "Learn from a video"
inline void showDialog(MainWindow *window)
{
    QDialog dialog(window);
    dialog.setObjectName(QStringLiteral("learnDialog"));
    dialog.setWindowTitle(QObject::tr("Learn from a video"));
    dialog.setMinimumWidth(560);
    auto column = new QVBoxLayout(&dialog);
    auto heading = new QLabel(QObject::tr("Learn from a video"), &dialog);
    heading->setObjectName(QStringLiteral("newVideoHeading"));
    heading->setStyleSheet(QStringLiteral("font-size: 22px; font-weight: 700;"));
    column->addWidget(heading);
    column->addWidget(new Panel(window, &dialog));
    auto close = new QPushButton(QObject::tr("Close"), &dialog);
    close->setObjectName(QStringLiteral("learnClose"));
    close->setAutoDefault(false);
    QObject::connect(close, &QPushButton::clicked, &dialog, &QDialog::accept);
    column->addWidget(close, 0, Qt::AlignRight);
    dialog.exec();
}

} // namespace LearnLooks

#endif
