/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The main window's letitedit actions: opening a video without taking the person's focus, the home screen's videos, How to, Shorts and the pause remover.
 * (letitedit's additions to mainwindow.cpp, moved out of Shotcut's file; the
 * declarations stay in its header.)
 */
#include "mainwindow.h"
#include "letitedit/home/videoprojects.h"
#include "letitedit/airoot.h"
#include "letitedit/chat/aichatpanel.h"
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
#include "letitedit/bridge/aicollaboration.h"
#include "letitedit/player/previewobjects.h"
#include "letitedit/player/phonezones.h"
#include "letitedit/chat/connectai.h"
#include "letitedit/newvideo/firstcut.h"
#include "letitedit/panels/hookpanel.h"
#include "letitedit/export/pauseremover.h"
#include "letitedit/panels/musicpicker.h"
#include "letitedit/export/chapters.h"
#include "letitedit/review/reviewmode.h"
#include "letitedit/export/othersizes.h"
#include "letitedit/panels/myassets.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/export/shortsmaker.h"
#include "letitedit/letitedit.h"
#include "letitedit/dialogs/lefeatures.h"
// (ui_mainwindow.h: not needed here; these functions use none of the form)

#include "Logger.h"
#include "actions.h"
#include "autosavefile.h"
#include "commands/playlistcommands.h"
#include "controllers/filtercontroller.h"
#include "controllers/scopecontroller.h"
#include "database.h"
#include "defaultlayouts.h"
#include "dialogs/actionsdialog.h"
#include "dialogs/customprofiledialog.h"
#include "dialogs/listselectiondialog.h"
#include "dialogs/longuitask.h"
#include "dialogs/resourcedialog.h"
#include "dialogs/saveimagedialog.h"
#include "dialogs/systemsyncdialog.h"
#include "dialogs/textviewerdialog.h"
#include "dialogs/unlinkedfilesdialog.h"
#include "docks/elementsdock.h"
#include "docks/encodedock.h"
#include "docks/filesdock.h"
#include "docks/filtersdock.h"
#include "docks/findanalysisfilterparser.h"
#include "docks/historyundoview.h"
#include "docks/jobsdock.h"
#include "docks/keyframesdock.h"
#include "docks/markersdock.h"
#include "docks/notesdock.h"
#include "docks/playlistdock.h"
#include "docks/recentdock.h"
#include "docks/subtitlesdock.h"
#include "docks/timelinedock.h"
#include "gpuinfo.h"
#include "hdrpreviewwindow.h"
#include "jobqueue.h"
#include "letitedit/workspace/leside.h"
#include "jobs/screencapturejob.h"
#include "models/audiolevelstask.h"
#include "models/keyframesmodel.h"
#include "models/motiontrackermodel.h"
#include "openotherdialog.h"
#include "player.h"
#include "proxymanager.h"
#include "qmltypes/qmlapplication.h"
#include "qmltypes/qmlprofile.h"
#include "qmltypes/qmlutilities.h"

#include <QQmlContext>
#include <QQmlEngine>
#include "screencapture/screencapture.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"
#include "util.h"
#include "videowidget.h"
#include "widgets/alsawidget.h"
#include "widgets/avformatproducerwidget.h"
#include "widgets/avfoundationproducerwidget.h"
#include "widgets/blipproducerwidget.h"
#include "widgets/colorbarswidget.h"
#include "widgets/colorproducerwidget.h"
#include "widgets/countproducerwidget.h"
#include "widgets/decklinkproducerwidget.h"
#include "widgets/directshowvideowidget.h"
#include "widgets/glaxnimateproducerwidget.h"
#include "widgets/htmlgeneratorwidget.h"
#include "widgets/imageproducerwidget.h"
#include "widgets/isingwidget.h"
#include "widgets/lissajouswidget.h"
#include "widgets/lumamixtransition.h"
#include "widgets/mltclipproducerwidget.h"
#include "widgets/newprojectfolder.h"
#include "widgets/noisewidget.h"
#include "widgets/plasmawidget.h"
#include "widgets/pulseaudiowidget.h"
#include "widgets/textproducerwidget.h"
#include "widgets/timelinepropertieswidget.h"
#include "widgets/toneproducerwidget.h"
#include "widgets/trackpropertieswidget.h"
#include "widgets/video4linuxwidget.h"
#ifdef Q_OS_WIN
#include "windowstools.h"
#endif

#include <QApplication>
#include <QClipboard>
#include <QDirIterator>
#include <QFileDialog>
#include <QHelpEvent>
#include <QImageReader>
#include <QJSEngine>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMutexLocker>
#include <QProcess>
#include <QRegularExpression>
#include <QScopeGuard>
#include <QQuickItem>
#include <QQuickWindow>
#include <QStandardPaths>
#include <QThreadPool>
#include <QTimer>
#include <QVersionNumber>
#include <QWhatsThis>
#include <QtConcurrent/QtConcurrentRun>
#include <QtNetwork>
#include <QtWidgets>

#include <algorithm>

// Is letitedit the app in front? Not Qt's isActiveWindow: the focus can sit in a child window of ours.
static bool letiteditInForeground()
{
    if (qEnvironmentVariableIsSet("LETITEDIT_QA_WINDOW_ACTIVE"))
        return true;
#ifdef Q_OS_WIN
    DWORD owner = 0;
    if (HWND front = GetForegroundWindow())
        GetWindowThreadProcessId(front, &owner);
    return owner == GetCurrentProcessId();
#else
    return QApplication::activeWindow() != nullptr;
#endif
}

void MainWindow::openWithoutFocus(const QString &path)
{
    if (letiteditInForeground()) {
        open(path);   // already in front: exactly as a person's open, which keeps it active
        m_lastOpenFocus = QStringLiteral("already-foreground");
        return;
    }
    m_openQuietly = true;
    const auto done = qScopeGuard([this]() { m_openQuietly = false; });
    open(path);
    keepBehindForeground();
    QApplication::alert(this);
    m_lastOpenFocus = QStringLiteral("no-activate-flashed");
}

// A new window of ours shown without activating still lands on top: put it just under the app in front.
void MainWindow::keepBehindForeground()
{
#ifdef Q_OS_WIN
    if (HWND front = GetForegroundWindow()) {
        HWND self = reinterpret_cast<HWND>(winId());
        if (front != self)
            SetWindowPos(self, front, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    }
#endif
}

void MainWindow::openHomeVideo(const QString &path)
{
    const QFileInfo info(path);
    if (info.suffix().compare(QStringLiteral("mlt"), Qt::CaseInsensitive) == 0
        || info.suffix().compare(QStringLiteral("xml"), Qt::CaseInsensitive) == 0) {
        openMultiple(QStringList{path});
        return;
    }
    if (!m_currentFile.isEmpty() || isWindowModified()) {
        showStatusMessage(tr("Close the current video before starting another."), 10);
        return;
    }
    if (!open(path, nullptr, false) || !MLT.producer() || !MLT.producer()->is_valid() || !MLT.isSeekableClip()) {
        showStatusMessage(tr("Couldn't open this video."), 10);
        return;
    }
    const QString folder = VideoProjects::create(info.completeBaseName());
    if (folder.isEmpty()) {
        showStatusMessage(tr("Couldn't make a folder for this video. Choose a writable Projects folder in Settings."), 15);
        return;
    }
    const QString xml = MLT.XML(MLT.producer());
    m_timelineDock->insert(-1, 0, xml);
    seekTimeline(0);
    newProject(QDir(folder).filePath(QFileInfo(folder).fileName() + QStringLiteral(".mlt")));
}

// "Edit with the AI myself" (New video) and "Start with an empty timeline" (Home): a project of its own in the Projects
// folder at the format's size (bridge\start_project.py), the chosen clips in the bin and on the timeline in this order,
// opened here with the chat ready. No AI run starts and the footage stays where it is.
void MainWindow::openEditorWithClips(const QString &kind, const QStringList &files, const QString &name)
{
    QString title = name.trimmed();
    if (title.isEmpty())
        title = files.size() == 1 ? QFileInfo(files.first()).completeBaseName()
                                  : files.isEmpty() ? tr("My video") : QFileInfo(QFileInfo(files.first()).absolutePath()).fileName();
    const QString folder = VideoProjects::create(title);
    if (folder.isEmpty()) {
        showStatusMessage(tr("Couldn't make a folder for this video. Choose a writable Projects folder in Settings."), 15);
        return;
    }
    auto *process = new QProcess(this);
    process->setProcessChannelMode(QProcess::SeparateChannels);
    connect(process, &QProcess::finished, this, [this, process, folder, files](int code, QProcess::ExitStatus status) {
        process->deleteLater();
        const QByteArray out = process->readAllStandardOutput().trimmed();
        const QJsonObject result = QJsonDocument::fromJson(out.split('\n').last()).object();
        const QString project = result.value(QStringLiteral("project")).toString();
        if (status != QProcess::NormalExit || code != 0 || project.isEmpty() || !QFileInfo(project).isFile()) {
            LOG_WARNING() << "start_project failed" << result.value(QStringLiteral("error")).toString() << out;
            QDir(folder).removeRecursively();
            showStatusMessage(tr("Couldn't start this video. Try again in a moment."), 15);
            return;
        }
        if (!open(project, nullptr, false))
            return; // the person kept the video that was open (Shotcut's own save question)
        const int clips = result.value(QStringLiteral("clips")).toInt();
        const int skipped = result.value(QStringLiteral("skipped")).toArray().size();
        QString note = clips == 1 ? tr("Your clip is in. Ask me for anything you want done.")
                       : clips > 1 ? tr("Your %1 clips are in, in the order you chose. Ask me for anything you want done.").arg(clips)
                                   : tr("Your empty timeline is ready. Add clips, or ask me for anything you want done.");
        if (skipped > 0)
            note += QLatin1Char(' ') + (skipped == 1 ? tr("One file couldn't be read and was left out.")
                                                     : tr("%1 files couldn't be read and were left out.").arg(skipped));
        aiChatShowReady(project, note);
    });
    QStringList args{aiRootPath(QStringLiteral("bridge/start_project.py")), QStringLiteral("--folder"), folder,
                     QStringLiteral("--kind"), kind == QLatin1String("long") ? QStringLiteral("long") : QStringLiteral("short")};
    args << files;
    process->start(aiChatSettings().value(QStringLiteral("python")).toString(), args);
}

void MainWindow::removePauses()
{
    if (!isMultitrackValid()) {
        showStatusMessage(tr("Add clips to the timeline first."));
        return;
    }
    auto model = m_timelineDock->model();
    for (int i = 0; i < model->trackList().size(); ++i) {
        if (m_timelineDock->isTrackLocked(i)) {
            showStatusMessage(tr("Unlock all tracks to remove pauses."));
            return;
        }
    }
    PauseRemover::Mode mode = PauseRemover::Normal;
    bool removeFillers = true;
    if (!PauseRemover::askOptions(this, mode, removeFillers))
        return;

    // The main track: V1, the lowest video track, where talking footage sits.
    int mltIndex = -1;
    for (const auto &track : model->trackList()) {
        if (track.type == VideoTrackType && (mltIndex < 0 || track.number == 0))
            mltIndex = track.mlt_index;
    }
    QScopedPointer<Mlt::Producer> trackProducer(model->tractor()->track(mltIndex));
    if (!trackProducer || !trackProducer->is_valid())
        return;
    Mlt::Playlist playlist(*trackProducer);
    struct Clip
    {
        int start;
        int frameIn;
        int frameCount;
        QString resource;
    };
    QList<Clip> clips;
    for (int i = 0; i < playlist.count(); ++i) {
        QScopedPointer<Mlt::ClipInfo> info(playlist.clip_info(i));
        if (!info || playlist.is_blank(i) || !info->producer)
            continue;
        const QString resource = QString::fromUtf8(info->producer->get("resource"));
        if (QFileInfo(resource).isFile() && info->producer->get_int("audio_index") >= 0)
            clips.append({info->start, info->frame_in, info->frame_count, resource});
    }
    if (clips.isEmpty()) {
        showStatusMessage(tr("No clips with sound on the main video track."));
        return;
    }

    const double fps = MLT.profile().fps();
    const QString ffmpeg = QDir(qApp->applicationDirPath()).filePath("ffmpeg");
    // whisper-cli's word alignment (DTW) protects quiet words, finds sentence ends and lone um/uh. Without a
    // speech model the cut still follows the sound level, which keeps soft word endings.
    const QString whisper = Settings.whisperExe();
    const QString speechModel = Settings.whisperModel();
    const QString preset = PauseRemover::alignmentPreset(speechModel);
    const bool canListen = !preset.isEmpty() && QFileInfo(whisper).isExecutable() && QFileInfo::exists(speechModel);
    const bool english = preset.endsWith(".en") || QLocale::system().language() == QLocale::English;
    QTemporaryDir temp;

    QProgressDialog progress(tr("Listening to the talking..."), tr("Cancel"), 0, clips.size() * 2, this);
    progress.setWindowTitle(tr("Remove Pauses"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);
    progress.setValue(0);
    const auto run = [&progress](const QString &program, const QStringList &args) {
        return leRun(program, args, &progress);
    };

    QList<QPair<int, int>> cuts; // timeline frames, end exclusive
    int fillersRemoved = 0, fillersKept = 0;
    bool listened = false;
    for (int c = 0; c < clips.size(); ++c) {
        const Clip &clip = clips[c];
        if (clips.size() > 1)
            progress.setLabelText(tr("Listening to clip %1 of %2...").arg(c + 1).arg(clips.size()));
        const QString wav = temp.filePath(QStringLiteral("clip%1.wav").arg(c));
        const bool extracted = run(ffmpeg,
                                   {"-hide_banner", "-nostats", "-loglevel", "error", "-y", "-ss",
                                    QString::number(clip.frameIn / fps, 'f', 3), "-t",
                                    QString::number(clip.frameCount / fps, 'f', 3), "-i", clip.resource, "-map",
                                    "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav});
        if (progress.wasCanceled())
            return;
        progress.setValue(c * 2 + 1);
        if (!extracted)
            continue;
        QList<PauseRemover::Word> words;
        if (canListen) {
            const QString base = temp.filePath(QStringLiteral("clip%1").arg(c));
            QStringList args{"-m", speechModel, "-f", wav, "-l", english ? "en" : "auto", "-oj", "-ojf", "-dtw",
                             preset, "-nfa", "-np", "-of", base, "-t",
                             QString::number(qMax(1, QThread::idealThreadCount() - 1))};
            // This prompt makes whisper write down um and uh (it skips them otherwise) and punctuate.
            if (english)
                args << "--prompt" << "Umm, let me think like, hmm... Okay, here's what I'm, like, thinking.";
            if (!Settings.whisperUseGpu())
                args << "--no-gpu";
            if (run(whisper, args))
                words = PauseRemover::words(base + ".json");
            if (progress.wasCanceled())
                return;
        }
        for (const auto &w : words) {
            if (w.time >= 0.0) {
                listened = true;
                break;
            }
        }
        progress.setValue(c * 2 + 2);
        const auto plan = PauseRemover::plan(PauseRemover::loudness(wav), words, mode, removeFillers);
        fillersRemoved += plan.fillersRemoved;
        fillersKept += plan.fillersKept;
        for (const auto &cut : plan.cuts) {
            const int from = clip.start + qRound(cut.from * fps);
            const int to = clip.start + qMin(qRound(cut.to * fps), clip.frameCount);
            if (to - from >= 2)
                cuts.append({from, to});
        }
        LOG_INFO() << "remove pauses:" << clip.resource << plan.cuts.size() << "cuts," << plan.fillersRemoved
                   << "fillers cut," << plan.fillersKept << "kept, words" << words.size();
    }
    progress.close();

    QString kept;
    if (removeFillers && fillersKept > 0)
        kept = tr("%n um or uh run straight into a word, so they stay.", nullptr, fillersKept);
    else if (removeFillers && !listened)
        kept = tr("No speech model, so um and uh stay.");
    if (cuts.isEmpty()) {
        showStatusMessage((tr("No pauses long enough to cut.") + ' ' + kept).trimmed(), 10);
        return;
    }
    applyPauseCuts(model, cuts, fps, fillersRemoved, kept);
}

void MainWindow::applyPauseCuts(MultitrackModel *model, const QList<QPair<int, int>> &cuts, double fps,
                                int fillersRemoved, const QString &kept)
{
    // Every cut moves every track, captions and markers together, in one undo step. Music is not cut: a
    // song chopped at every pause jumps. Music from Add music is fitted again to the shorter video, so it
    // still dips under the talking where that now is and ends with its fade; other music plays on and ends
    // with the video, faded out.
    QSet<int> music;
    QMap<int, MusicPicker::Options> refit;
    for (int i = 0; i < model->trackList().size(); ++i) {
        if (model->trackList().at(i).type != AudioTrackType)
            continue;
        QScopedPointer<Mlt::Producer> track(model->tractor()->track(model->trackList().at(i).mlt_index));
        if (!track || !track->is_valid()
            || !MusicPicker::isMusicName(QString::fromUtf8(track->get(kTrackNameProperty))))
            continue;
        music << i;
        MusicPicker::Options options;
        if (MusicPicker::fitted(this, i, options))
            refit.insert(i, options);
    }
    int removed = 0;
    for (const auto &cut : cuts)
        removed += cut.second - cut.first;
    bool musicFitted = false, musicFaded = false;
    m_undoStack->beginMacro(tr("Remove pauses"));
    auto *command = new AiDeleteSectionsCommand(m_timelineDock, cuts, fps, music, tr("Remove pauses"));
    m_undoStack->push(command);
    for (int track : std::as_const(music)) {
        if (refit.contains(track) && !MusicPicker::apply(this, refit.value(track)).isEmpty()) {
            musicFitted = true;
            continue;
        }
        if (!command->wasShortened(track))
            continue;
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(model->trackList().at(track).mlt_index));
        Mlt::Playlist playlist(*producer);
        int last = playlist.count() - 1;
        while (last >= 0 && playlist.is_blank(last))
            --last;
        if (last >= 0) {
            m_timelineDock->fadeOut(track, last, qMin(qRound(2.0 * fps), playlist.clip_length(last) / 2));
            musicFaded = true;
        }
    }
    m_undoStack->endMacro();
    const QString seconds = QString::number(removed / fps, 'f', 1);
    QString done = fillersRemoved > 0
                       ? tr("Cut %1 pauses and %2 um/uh: %3 seconds shorter.")
                             .arg(cuts.size())
                             .arg(fillersRemoved)
                             .arg(seconds)
                       : tr("Cut %1 pauses: %2 seconds shorter.").arg(cuts.size()).arg(seconds);
    if (musicFitted)
        done += ' ' + tr("The music was fitted to the new length.");
    else if (musicFaded)
        done += ' ' + tr("The music plays on and now ends with the video.");
    showStatusMessage((done + ' ' + kept).trimmed() + ' ' + tr("Undo brings it all back."), 15);
}

void MainWindow::makeShort(const QStringList &chosen)
{
    QStringList paths = chosen;
    if (paths.isEmpty()) {
        paths = QFileDialog::getOpenFileNames(this,
                                              tr("Choose the clips for your short"),
                                              Settings.openPath(),
                                              tr("Videos and pictures (*.mp4 *.mov *.m4v *.mkv *.avi *.webm *.mts *.jpg *.jpeg *.png *.heic);;All files (*)"),
                                              nullptr,
                                              Util::getFileDialogOptions());
        if (paths.isEmpty())
            return;
        Settings.setOpenPath(QFileInfo(paths.first()).path());
    }
    if (!continueModified())
        return;
    setWindowModified(false);
    on_actionClose_triggered();

    // 1080x1920 at the first clip's frame rate (phones record 29.97/59.94); 30 when it is unusual.
    Mlt::Profile probeProfile;
    Mlt::Producer probe(probeProfile, paths.first().toUtf8().constData());
    const bool usable = probe.is_valid() && (probeProfile.from_producer(probe), true)
                        && probeProfile.fps() >= 23.0 && probeProfile.fps() <= 61.0;
    setProfile(usable && probeProfile.fps() > 45.0 ? "vertical_hd_60" : "vertical_hd_30");
    if (usable)
        MLT.profile().set_frame_rate(probeProfile.frame_rate_num(), probeProfile.frame_rate_den());
    MLT.profile().set_explicit(true);

    Mlt::Playlist playlist(MLT.profile());
    QStringList skipped;
    for (const auto &path : paths) {
        Mlt::Producer raw(MLT.profile(), path.toUtf8().constData());
        if (!raw.is_valid() || raw.get_length() <= 0) {
            skipped << QFileInfo(path).fileName();
            continue;
        }
        // Configured like a drag-and-drop from Explorer.
        QScopedPointer<Mlt::Producer> producer(MLT.setupNewProducer(&raw));
        producer->set(kShotcutCaptionProperty, QFileInfo(path).fileName().toUtf8().constData());
        // Fill the 9:16 frame instead of letterboxing: Crop: Source, centred on the project's shape.
        // It stays an ordinary editable filter on the clip.
        Mlt::Filter crop(MLT.profile(), "crop");
        crop.set("use_profile", 1);
        crop.set("center", 1);
        crop.set("center_bias", 0);
        producer->attach(crop);
        playlist.append(*producer);
    }
    if (playlist.count() == 0) {
        QMessageBox::warning(this,
                             tr("Make a Vertical Short"),
                             tr("None of the chosen files could be opened as video or pictures."));
        return;
    }
    onAddAllToTimeline(&playlist, false, false);
    // Show the new timeline in the player, from the start.
    if (isMultitrackValid())
        seekTimeline(0);
    if (!skipped.isEmpty())
        QMessageBox::warning(this,
                             tr("Make a Vertical Short"),
                             tr("These files could not be opened and were left out:\n%1")
                                 .arg(skipped.join("\n")));
    showStatusMessage(tr("Your short is on the timeline (1080x1920). Next: add captions."), 10);
}

// letitedit's own How to (the Command Finder, AI menu): where each button is and what it does. Without it, the website.
void MainWindow::openHowTo()
{
    const auto actions = findChildren<QAction *>(QStringLiteral("aiAssistCommandHelp"));
    if (!actions.isEmpty()) {
        actions.first()->trigger();
        return;
    }
    Util::openUrl(QUrl("https://letitedit.app"));
}
