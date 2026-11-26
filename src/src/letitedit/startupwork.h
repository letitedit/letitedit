#ifndef LETITEDIT_STARTUPWORK_H
#define LETITEDIT_STARTUPWORK_H

#include <QObject>
#include <QStringList>

#include <atomic>
#include <functional>

class QThread;

// letitedit: the heavy part of starting the editor, done behind a window that answers (T288; the owner's rule "the app
// never freezes"). The bundled fonts (about 800 files) are read ahead on a worker thread and added to the application
// a few at a time on the window's thread, and the filters' descriptions are compiled by Qt's own QML loader thread
// (FilterController). Until both are done, the editor opens no project and its AI bridge holds requests: whenReady()
// runs work once they are.
class StartupWork : public QObject
{
    Q_OBJECT

public:
    static StartupWork &instance();

    // Starts loading every font file in these folders (QFontDatabase::addApplicationFont; a file name seen in an
    // earlier folder is skipped). Returns at once.
    void loadFonts(const QStringList &dirs);
    // On the first open of this build for this account (no marker in markerPath, which names the build), reads the
    // engine's modules, the program's libraries and its QML once on worker threads, so the window's thread doesn't pay
    // a fresh install's first reads (the antivirus checks each file once) one file at a time. Returns at once.
    void readAheadFirstOpen(const QString &appDir, const QString &markerPath);
    // The engine is loaded: the fonts' reader waits while the main window is made (until setWindowUp), the read-ahead
    // until the fonts and filters are loaded (ready()); then they read at the lowest disk priority.
    void setEngineLoaded();
    // The main window is up and its event loop runs: the fonts' reader goes on.
    void setWindowUp();
    // The filters' descriptions are loaded (FilterController::metadataLoaded).
    void setFiltersLoaded();
    bool isReady() const { return m_fontsLoaded && m_filtersLoaded; }
    // Runs f on the window's thread now if the start-up work is done, else once it is (never if context goes first).
    void whenReady(QObject *context, std::function<void()> f);

signals:
    void ready();

private:
    explicit StartupWork(QObject *parent = nullptr);
    ~StartupWork() override;
    void stopWorker();
    void addSomeFonts();
    void fontsDone();
    void checkReady();

    QStringList m_dirs;
    QStringList m_files;           // found by the worker, in the order they are added
    std::atomic<int> m_readAhead{0}; // how many of m_files the worker has read into memory once (warms the disk cache)
    std::atomic<bool> m_listed{false};
    std::atomic<bool> m_stop{false};
    std::atomic<bool> m_engineLoaded{false};
    std::atomic<bool> m_holdFonts{false};     // from the engine loaded to the window up
    std::atomic<bool> m_holdReadAhead{false}; // from the engine loaded to the fonts and filters loaded
    void waitWhileHeld(const std::atomic<bool> &hold) const;
    std::atomic<bool> m_mainWaiting{false}; // the window's thread caught up with the worker and waits for its call
    int m_next = 0;
    int m_loaded = 0;
    int m_failed = 0;
    qint64 m_startedMs = 0;
    bool m_fontsLoaded = false;
    bool m_filtersLoaded = false;
    QThread *m_worker = nullptr;
    QList<QThread *> m_readers;
    std::atomic<int> m_readersLeft{0};
};

#endif // LETITEDIT_STARTUPWORK_H
