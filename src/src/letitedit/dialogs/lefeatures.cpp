/*
 * Copyright (c) 2026 Meltytech, LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/dialogs/featurehelpers.h"

#include "Logger.h"
#include "actions.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "letitedit/chat/connectai.h"
#include "docks/timelinedock.h"
#include "letitedit/workspace/focusworkspace.h"
#include "letitedit/panels/imagegen.h"
#include "letitedit/letitedit.h"
#include "letitedit/dialogs/letools.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/multitrackmodel.h"
#include "letitedit/panels/mystyle.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"
#include "letitedit/panels/stickerspanel.h"
#include "util.h"

#include <QApplication>
#include <QButtonGroup>
#include <QClipboard>
#include <QComboBox>
#include <QDateTime>
#include <QDesktopServices>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QDockWidget>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPointer>
#include <QProgressBar>
#include <QPushButton>
#include <QRegularExpression>
#include <QRadioButton>
#include <QScrollArea>
#include <QStandardPaths>
#include <QStyle>
#include <QTemporaryDir>
#include <QTextBrowser>
#include <QTimer>
#include <QUndoStack>
#include <QUrl>
#include <QVBoxLayout>

#include <functional>

namespace LeFeatures {

// The dialogs themselves are letitedit/dialogs/, one file each (featurehelpers.h is what they share).

const QStringList kVideoFiles{"*.mp4", "*.mov", "*.m4v", "*.mkv", "*.webm", "*.avi", "*.mts", "*.mxf"};
const QStringList kSoundFiles{"*.wav", "*.mp3", "*.m4a", "*.flac", "*.aac", "*.ogg"};

QLabel *headingLabel(const QString &text, QWidget *parent)
{
    auto label = new QLabel(text, parent);
    label->setProperty("studioHeading", true);
    label->setWordWrap(true);
    return label;
}

QLabel *mutedLabel(const QString &text, QWidget *parent)
{
    auto label = new QLabel(text, parent);
    label->setProperty("studioMuted", true);
    label->setWordWrap(true);
    return label;
}

QString nativePath(const QString &path)
{
    return QDir::toNativeSeparators(path);
}

void showChat(MainWindow *window)
{
    if (auto chat = window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
        chat->show();
        chat->raise();
    }
}

// One request to the person's AI: the chat shows `summary`, the AI gets `text`. False when it couldn't take it.
bool ask(MainWindow *window, const QString &text, const QString &summary, const QString &busyLine)
{
    if (!aiChatRequest(window, text, summary)) {
        window->showStatusMessage(QObject::tr("Your AI is still busy with the last request. Try again when it has "
                                              "answered (or press Stop in the chat)."),
                                  10);
        return false;
    }
    showChat(window);
    window->showStatusMessage(busyLine, 12);
    return true;
}

// The paths in a "folder or files" field: one folder, or files separated by ';'.
QStringList pathsIn(const QString &text)
{
    QStringList out;
    for (const auto &part : text.split(QLatin1Char(';'), Qt::SkipEmptyParts)) {
        QString p = part.trimmed();
        if (p.startsWith(QLatin1Char('"')) && p.endsWith(QLatin1Char('"')) && p.size() > 1)
            p = p.mid(1, p.size() - 2);
        if (!p.isEmpty())
            out << p;
    }
    return out;
}

// What a folder or a list of files holds, in words ("3 videos and 1 sound file"); counts are returned too.
QString countFiles(const QStringList &paths, int *videos, int *sounds)
{
    int v = 0, s = 0;
    auto add = [&](const QString &file) {
        const QString name = QFileInfo(file).fileName();
        if (QDir::match(kVideoFiles, name))
            ++v;
        else if (QDir::match(kSoundFiles, name))
            ++s;
    };
    for (const auto &p : paths) {
        const QFileInfo info(p);
        if (info.isDir()) {
            for (const auto &f : QDir(p).entryList(kVideoFiles + kSoundFiles, QDir::Files))
                add(f);
        } else if (info.isFile()) {
            add(p);
        }
    }
    if (videos)
        *videos = v;
    if (sounds)
        *sounds = s;
    QStringList parts;
    if (v)
        parts << (v == 1 ? QObject::tr("1 video") : QObject::tr("%1 videos").arg(v));
    if (s)
        parts << (s == 1 ? QObject::tr("1 sound file") : QObject::tr("%1 sound files").arg(s));
    return parts.join(QObject::tr(" and "));
}

namespace {

// ------------------------------------------------------------------------------------------------ Import a style

// ------------------------------------------------------------------------------------------------ Animated title

// ------------------------------------------------------------------------------------------------ Line up separate sound

// ------------------------------------------------------------------------------------------------ Check my video

// ------------------------------------------------------------------------------------------------ Dub this video

void attachBox(Mlt::Producer &producer, double size)
{
    const int pw = MLT.profile().width(), ph = MLT.profile().height();
    const int side = qMax(16, qRound(qMin(pw, ph) * size));
    int mw = producer.get_int("meta.media.width"), mh = producer.get_int("meta.media.height");
    if (mw <= 0 || mh <= 0)
        mw = mh = 1;
    const QSize box = QSize(mw, mh).scaled(side, side, Qt::KeepAspectRatio);
    const QString rect = QStringLiteral("%1 %2 %3 %4 1.0")
                             .arg((pw - box.width()) / 2)
                             .arg((ph - box.height()) / 2)
                             .arg(box.width())
                             .arg(box.height());
    const bool gpu = Settings.playerGPU();
    Mlt::Filter f(MLT.profile(), gpu ? "movit.rect" : "affine");
    if (!f.is_valid())
        return;
    if (gpu) {
        f.set("rect", rect.toLatin1().constData());
        f.set("fill", 1);
        f.set("distort", 0);
        f.set("valign", "middle");
        f.set("halign", "center");
    } else {
        f.set("transition.rect", rect.toLatin1().constData());
        f.set("transition.fill", 1);
        f.set("transition.distort", 0);
        f.set("transition.valign", "middle");
        f.set("transition.halign", "center");
        f.set("transition.threads", 0);
        f.set("background", "color:#00000000");
    }
    f.set(kShotcutFilterProperty, gpu ? "movitSizePosition" : "affineSizePosition");
    producer.attach(f);
}

} // namespace

// ------------------------------------------------------------------------------------------------ the public part

void showStickers(MainWindow *window, const QString &kinds)
{
    auto panel = static_cast<StickersPanel *>(window->findChild<QDockWidget *>(QStringLiteral("stickersDock")));
    if (!panel)
        return;
    for (auto d : window->findChildren<QDockWidget *>()) {
        if (d != panel && d->isVisible() && !d->isFloating() && window->dockWidgetArea(d) == Qt::LeftDockWidgetArea)
            d->hide();
    }
    const bool needsRoom = !panel->isVisible() || !panel->isFloating();
    if (!panel->isFloating())
        window->addDockWidget(Qt::LeftDockWidgetArea, panel);
    panel->show();
    panel->setFloating(true);
    if (needsRoom) {
        // Browse in a window large enough to see several rows, even on a laptop.
        // Leave the lower part of the editor visible as a drag target.
        panel->resize(qMin(1260, qMax(700, window->width() * 72 / 100)),
                      qMin(820, qMax(440, window->height() * 72 / 100)));
        panel->move(window->x() + 24, window->y() + 42);
    }
    panel->raise();
    panel->showKinds(kinds);
}

bool askCleanVoice(MainWindow *window)
{
    if (!window->multitrack()) {
        window->showStatusMessage(QObject::tr("Put your clips on the timeline first, then clean up the voice."), 10);
        return false;
    }
    if (window->fileName().isEmpty()) {
        QMessageBox::information(window, QObject::tr("Clean up the voice"),
                                 QObject::tr("Save your video first (Menu > File > Save): your AI cleans up the voice "
                                             "in the saved project. Then press Clean up the voice again."));
        return false;
    }
    const bool selected = !window->timelineDock()->selection().isEmpty();
    const QString which = selected ? QObject::tr("the clips I selected") : QObject::tr("the clips where someone talks");
    const QString text
        = QObject::tr("Clean up the voice in %1 in my open project %2: use letitedit_fix with fix 'voice' and "
                      "action 'apply' on each of those clips (its gentle defaults, so the voice stays natural; never "
                      "above atten_lim_db 18). The defaults lower everything but speech, so decide for yourself, clip "
                      "by clip, whether a sound other than the voice matters in it (a tool, a machine, music or "
                      "ambience the video is about) by measuring the gaps between its words, not by guessing from "
                      "what is talked about, and don't ask me. Where one does, use separate true on that clip so the sound keeps its "
                      "level, and tell me which clips you protected. Then listen "
                      "to a few seconds before and after with "
                      "letitedit_check_audio and tell me in one or two lines what changed. Every change is one Undo "
                      "step.")
              .arg(which, nativePath(window->fileName()));
    return ask(window, text,
               selected ? QObject::tr("Clean up the voice in the selected clips")
                        : QObject::tr("Clean up the voice in this video"),
               QObject::tr("Your AI is cleaning up the voice (a few minutes); it says in the chat when it's done."));
}

bool askReframe(MainWindow *window, const QString &video, const QStringList &shapes)
{
    const QString project = window->fileName();
    if (project.isEmpty())
        return false;
    QStringList words;
    for (const auto &s : shapes)
        words << QString(s).replace(QLatin1Char('x'), QLatin1Char(':'));
    const QString text
        = QObject::tr("Make %1 versions of my project %2 that keep the people in frame: use letitedit_versions with "
                      "reframe {mode: 'solve'} (letitedit_reframe keeps faces, hands and what is being shown inside "
                      "the crop, and offers a split or an inset where two people can't share one), re-fit the "
                      "captions, check the frames, export each version next to %3 and tell me where they are. Don't "
                      "change the main project.")
              .arg(words.join(QStringLiteral(", ")), nativePath(project), nativePath(video));
    return ask(window, text, QObject::tr("Make %1 versions that keep people in frame").arg(words.join(QStringLiteral(", "))),
               QObject::tr("Your AI is making the other sizes; it says in the chat where they are."));
}

QString producerXml(const QString &file, bool audio, const QString &asset, double seconds, double size, QString *why,
                    const QString &caption)
{
    Mlt::Producer producer(MLT.profile(), file.toUtf8().constData());
    if (!producer.is_valid()) {
        if (why)
            *why = QObject::tr("letitedit can't read %1.").arg(QFileInfo(file).fileName());
        return QString();
    }
    if (!asset.isEmpty())
        producer.set("letitedit:asset", asset.toUtf8().constData()); // the credit lines find it by this
    if (!caption.isEmpty())
        producer.set(kShotcutCaptionProperty, caption.toUtf8().constData());
    static const QStringList stills{"png", "jpg", "jpeg", "webp", "svg", "bmp"};
    if (!audio && stills.contains(QFileInfo(file).suffix().toLower())) {
        MLT.setDurationFromDefault(&producer);
        const int frames = qMax(1, qRound((seconds > 0 ? seconds : 3.0) * MLT.profile().fps()));
        producer.set("length", frames);
        producer.set_in_and_out(0, frames - 1);
    }
    if (!audio && size > 0)
        attachBox(producer, size);
    return MLT.XML(&producer);
}

bool placeAtPlayhead(MainWindow *window, const QString &xml, bool audio, const QString &trackName, const QString &label,
                     QString *why)
{
    auto tl = window->timelineDock();
    auto model = tl->model();
    if (!model->tractor()) {
        if (why)
            *why = QObject::tr("Put a video on the timeline first, then add this.");
        return false;
    }
    Mlt::Producer producer(MLT.profile(), "xml-string", xml.toUtf8().constData());
    if (!producer.is_valid()) {
        if (why)
            *why = QObject::tr("That couldn't be added.");
        return false;
    }
    const int start = qMax(0, tl->position());
    const int frames = qMax(1, producer.get_playtime());
    const TrackType type = audio ? AudioTrackType : VideoTrackType;
    int target = -1;
    for (int t = 0; t < model->trackList().size(); ++t) {
        if (model->trackList()[t].type != type || tl->isTrackLocked(t) || model->getTrackName(t) != trackName)
            continue;
        bool free = true;
        for (int c = 0; c < model->rowCount(model->index(t)); ++c) {
            auto info = model->getClipInfo(t, c);
            if (info && !info->producer->is_blank() && info->start < start + frames && info->start + info->frame_count > start) {
                free = false;
                break;
            }
        }
        if (free) {
            target = t;
            break;
        }
    }
    window->undoStack()->beginMacro(label);
    if (target < 0) {
        target = audio ? tl->addAudioTrack() : tl->addVideoTrack();
        tl->setTrackName(target, trackName);
    }
    tl->overwrite(target, start, xml, false);
    window->undoStack()->endMacro();
    for (int c = 0; c < model->rowCount(model->index(target)); ++c) {
        auto info = model->getClipInfo(target, c);
        if (info && info->start == start && !info->producer->is_blank()) {
            tl->setSelection({QPoint(c, target)});
            break;
        }
    }
    return true;
}

QString projectCopy(MainWindow *window, const QString &file, const QString &name)
{
    const QString project = window->fileName();
    if (project.isEmpty() || !QFileInfo(file).isFile())
        return file;
    const QString folder = QFileInfo(project).absolutePath() + QStringLiteral("/Elements");
    // a plain name ("wrench.png", not the drawing's cache name); another file of that name gets "-2", "-3"...
    QString stem = name.trimmed();
    stem.replace(QRegularExpression(QStringLiteral("[\\\\/:*?\"<>|]+")), QStringLiteral("-"));
    if (stem.isEmpty())
        stem = QFileInfo(file).completeBaseName();
    const QString suffix = QFileInfo(file).suffix();
    QString target = folder + QLatin1Char('/') + stem + QLatin1Char('.') + suffix;
    for (int n = 2; QFileInfo::exists(target) && QFileInfo(target).size() != QFileInfo(file).size(); ++n)
        target = folder + QLatin1Char('/') + stem + QStringLiteral("-%1.").arg(n) + suffix;
    if (QFileInfo::exists(target))
        return target; // the same file, copied before
    QDir().mkpath(folder);
    return QFile::copy(file, target) ? target : file;
}

QJsonArray credits(MainWindow *window, int timeoutMs)
{
    if (!window || !window->multitrack() || leToolsPython().isEmpty())
        return {};
    QTemporaryDir temp;
    if (!temp.isValid())
        return {};
    const QString path = temp.filePath(QStringLiteral("timeline.mlt"));
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly))
        return {};
    file.write(MLT.XML(window->multitrack()).toUtf8());
    file.close();
    QByteArray out;
    if (!leRun(leToolsPython(), {aiRootPath(QStringLiteral("bridge/assets.py")), QStringLiteral("credits"), path},
               nullptr, &out, timeoutMs))
        return {};
    const int bracket = out.indexOf('[');
    return bracket >= 0 ? QJsonDocument::fromJson(out.mid(bracket)).array() : QJsonArray();
}

QString creditText(const QJsonArray &credits)
{
    QStringList lines;
    for (const auto &c : credits)
        lines << c.toObject().value("line").toString();
    return lines.join(QLatin1Char('\n'));
}

void rememberExport(const QString &video)
{
    leSettings().setValue(QStringLiteral("checkVideo/last"), video);
}

QString lastExport()
{
    const QString last = leSettings().value(QStringLiteral("checkVideo/last")).toString();
    return QFileInfo::exists(last) ? last : QString();
}

QJsonObject state()
{
    QJsonObject out;
    addAnimatedTitleState(out);
    addSyncSoundState(out);
    addCheckVideoState(out);
    if (auto panel = static_cast<StickersPanel *>(MAIN.findChild<QDockWidget *>(QStringLiteral("stickersDock"))))
        out.insert("stickers", panel->qaState());
    out.insert("last_export", lastExport());
    return out;
}

void install(MainWindow *window)
{
    QMenu *file = window->findChild<QMenu *>(QStringLiteral("menuFile"));
    QMenu *edit = window->findChild<QMenu *>(QStringLiteral("menuEdit"));
    QMenu *ai = window->findChild<QMenu *>(QStringLiteral("menuAi"));
    QAction *open = window->findChild<QAction *>(QStringLiteral("actionOpen"));
    auto add = [window](const char *name, const QString &text, const QString &tip, std::function<void()> fn) {
        auto action = new QAction(text, window);
        action->setObjectName(QString::fromLatin1(name));
        action->setToolTip(tip);
        QObject::connect(action, &QAction::triggered, window, [fn]() { fn(); });
        Actions.add(QString::fromLatin1(name), action, QObject::tr("AI"));
        return action;
    };
    QList<QAction *> fileActions, editActions;
    fileActions << add("learnLookAction", QObject::tr("Learn from a Video..."),
                       QObject::tr("Learn a reusable Look from one to three reference videos"),
                       [window]() { showLearn(window); });
    fileActions << add("syncSoundAction", QObject::tr("Line Up Separate Sound..."),
                       QObject::tr("Line up a separate mic, recorder or second camera with your clips by their sound"),
                       [window]() { showSyncSound(window); });
    fileActions << add("checkVideoAction", QObject::tr("Check My Video..."),
                       QObject::tr("Check the exported video: length, size, the first seconds, loudness, silences, "
                                   "captions and pace"),
                       [window]() { showCheckVideo(window); });
    editActions << add("stickersSoundsAction", QObject::tr("Elements..."),
                       QObject::tr("Open-source emoji, animated stickers, icons and sounds: search, then drag or add at the "
                                   "playhead"),
                       [window]() { showStickers(window); });
    editActions << add("imageGeneratorAction", QObject::tr("Image Generator..."),
                       QObject::tr("Describe a picture; your AI has it made and keeps it with this video"),
                       [window]() { ImageGenerator::show(window); });
    editActions << add("makeCodeSceneAction", QObject::tr("Make a scene here..."),
                       QObject::tr("Describe a scene for this moment; your AI writes and places it on the timeline"),
                       [window]() {
                           if (MAIN.fileName().isEmpty() || !MAIN.timelineDock()) {
                               window->showStatusMessage(QObject::tr("Open or save your video first."), 8);
                               return;
                           }
                           bool accepted = false;
                           const QString idea = QInputDialog::getMultiLineText(
                               window, QObject::tr("Make a scene here"),
                               QObject::tr("What should appear while this line or clip plays?\n"
                                           "For example: put me on a moonlit road while I say this."),
                               QString(), &accepted).trimmed();
                           if (!accepted || idea.isEmpty())
                               return;
                           const int frame = qMax(0, MAIN.timelineDock()->position());
                           const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
                           const QString request = QStringLiteral(
                               "Make a live Code scene in this project: %1. The playhead is at %2 seconds "
                               "(frame %3). The person's request is: %4\n"
                               "Read the words and selected clip around this moment with letitedit_editor, "
                               "letitedit_timeline_read and letitedit_words. Choose the exact line and timing. "
                               "Write fresh HyperFrames custom scene code and use letitedit_code_scene(create) "
                               "to put it on the Code scene track. Make its entrance, exit and any sound fit "
                               "the words; preserve factual honesty. Check the live result and tell the person "
                               "what you made.")
                               .arg(nativePath(MAIN.fileName()))
                               .arg(frame / fps, 0, 'f', 3)
                               .arg(frame)
                               .arg(idea);
                           ask(window, request, QObject::tr("Make a scene here: %1").arg(idea),
                               QObject::tr("Your AI is making the scene here…"));
                       });
    auto *view = window->findChild<QMenu *>(QStringLiteral("menuView"));
    if (view) {
        auto *library = add("ViewElements", QObject::tr("Elements"),
                            QObject::tr("Browse the open-source elements library"),
                            [window]() { showStickers(window); });
        library->setShortcut(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_2));
        view->addAction(library);
    }
    editActions << add("animatedTitleAction", QObject::tr("Animated Title..."),
                       QObject::tr("A moving title, name tag, place name, chapter card, count-up or end card"),
                       [window]() { showAnimatedTitle(window); });
    editActions << add("cleanVoiceAction", QObject::tr("Clean Up the Voice..."),
                       QObject::tr("Your AI takes out background noise and room echo from the talking, gently"),
                       [window]() { askCleanVoice(window); });
    editActions << add("dubVideoAction", QObject::tr("Dub This Video..."),
                       QObject::tr("Your AI translates what's said and a voice speaks it in another language, on its "
                                   "own track"),
                       [window]() { showDub(window); });
    if (file) {
        for (auto a : fileActions)
            open ? file->insertAction(open, a) : file->addAction(a);
    }
    if (edit) {
        for (auto a : editActions)
            edit->addAction(a);
    }
    if (ai) {
        ai->addSeparator();
        for (auto a : fileActions + editActions)
            ai->addAction(a);
    }
    auto panel = new StickersPanel(window);
    window->addDockWidget(Qt::LeftDockWidgetArea, panel);
    panel->hide();
    if (auto *old = window->findChild<QDockWidget *>(QStringLiteral("ElementsDock")))
        old->hide();
}

} // namespace LeFeatures
