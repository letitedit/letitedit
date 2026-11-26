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

#include "letitedit/review/reviewmode.h"

#include "letitedit/review/reviewwindow.h"

// Review itself is letitedit/review/ (the window, its parts and Live Review inside it); here are the entry
// points and the banners and offers around it.

namespace ReviewMode {


// Review closed with Live Review notes still going or changes not in yet: a line over the player. It never loads by
// itself here: the person may be editing by hand.
void showLiveBanner(MainWindow *window)
{
    using namespace LetItEditColors;
    auto session = LiveReview::Session::existing(window);
    auto layout = qobject_cast<QBoxLayout *>(window->player()->layout());
    if (!session || !layout || session->waiting() + session->working() + session->ready() == 0)
        return;
    if (auto old = window->player()->findChild<QWidget *>(QStringLiteral("liveReviewBanner")))
        delete old;
    auto banner = new QWidget(window->player());
    banner->setObjectName(QStringLiteral("liveReviewBanner"));
    banner->setAttribute(Qt::WA_StyledBackground, true);
    banner->setStyleSheet(QStringLiteral("QWidget#liveReviewBanner { background: %1; border: 1px solid %2; border-radius: 10px; }"
                                         "QLabel#liveReviewBannerText { color: %3; font-size: 13px; }")
                              .arg(tealDeep, teal, cream));
    auto row = new QHBoxLayout(banner);
    row->setContentsMargins(14, 8, 10, 8);
    row->setSpacing(10);
    auto text = new QLabel(banner);
    text->setObjectName(QStringLiteral("liveReviewBannerText"));
    text->setWordWrap(true);
    row->addWidget(text, 1);
    auto load = new QPushButton(QObject::tr("Bring them in"), banner);
    load->setObjectName(QStringLiteral("liveReviewBannerLoad"));
    load->setProperty("studioPrimary", true);
    row->addWidget(load);
    auto back = new QPushButton(QObject::tr("Back to Review"), banner);
    back->setObjectName(QStringLiteral("liveReviewBannerBack"));
    row->addWidget(back);
    layout->insertWidget(0, banner);
    const auto update = [banner, session, text, load]() {
        const int ready = session->ready(), going = session->waiting() + session->working();
        if (!ready && !going) {
            banner->deleteLater();
            return;
        }
        text->setText(going ? (ready ? QObject::tr("<b>Live Review:</b> %1 ready, %2 still working.").arg(ready).arg(going)
                                     : QObject::tr("<b>Live Review:</b> %1 still working.").arg(going))
                            : ready == 1 ? QObject::tr("<b>Live Review:</b> your change is ready.")
                                         : QObject::tr("<b>Live Review:</b> all %1 changes are ready.").arg(ready));
        load->setVisible(ready > 0 && !session->loading());
    };
    update();
    QObject::connect(session, &LiveReview::Session::changed, banner, update);
    QObject::connect(load, &QPushButton::clicked, banner, [window, session]() {
        session->load([window](double, const QString &problem) {
            if (!problem.isEmpty())
                window->showStatusMessage(QObject::tr("A change couldn't come in: %1").arg(problem));
        });
    });
    QObject::connect(back, &QPushButton::clicked, banner, [window]() { ReviewMode::show(window); });
}

// After sending: a line over the video says the notes went to the AI and where the video before them is. When that
// request's answer ends, it says what really happened - the changes the AI's tools made in this window (their Undo
// labels), a reply without changes, a stop or a failure - with the AI's answer, and offers what fits: watch the result,
// mark it up again, or send the same notes again.
void showSentBanner(MainWindow *window, int count, const QString &before, int request, const QString &requestText,
                    const QString &summary)
{
    using namespace LetItEditColors;
    auto layout = qobject_cast<QBoxLayout *>(window->player()->layout());
    if (!layout)
        return;
    if (auto old = window->player()->findChild<QWidget *>(QStringLiteral("reviewBanner")))
        old->deleteLater();
    auto banner = new QWidget(window->player());
    banner->setObjectName(QStringLiteral("reviewBanner"));
    banner->setAttribute(Qt::WA_StyledBackground, true);
    banner->setStyleSheet(QStringLiteral("QWidget#reviewBanner { background: %1; border: 1px solid %2; border-radius: 10px; }"
                                         "QLabel#reviewBannerText { color: %3; font-size: 13px; }")
                              .arg(tealDeep, teal, cream));
    banner->setProperty("request", request);
    auto row = new QHBoxLayout(banner);
    row->setContentsMargins(14, 8, 10, 8);
    row->setSpacing(10);
    auto text = new QLabel(banner);
    text->setObjectName(QStringLiteral("reviewBannerText"));
    text->setWordWrap(true);
    text->setText(QObject::tr("Sent %1 to your AI. It's working on it now; each change it makes is one Undo step. The "
                              "video before them is kept as “%2” (Versions of This Video).")
                      .arg(count == 1 ? QObject::tr("1 note") : QObject::tr("%1 notes").arg(count), before));
    row->addWidget(text, 1);
    auto watch = new QPushButton(QObject::tr("Watch it"), banner);
    watch->setObjectName(QStringLiteral("reviewBannerWatch"));
    watch->setProperty("studioPrimary", true);
    watch->hide();
    QObject::connect(watch, &QPushButton::clicked, banner, [window, banner]() {
        window->seekTimeline(0);
        window->player()->play();
        banner->deleteLater();
    });
    row->addWidget(watch);
    auto resend = new QPushButton(QObject::tr("Send again"), banner);
    resend->setObjectName(QStringLiteral("reviewBannerResend"));
    resend->setToolTip(QObject::tr("Send the same notes to your AI again (your notes and pictures are kept)"));
    resend->hide();
    QObject::connect(resend, &QPushButton::clicked, banner, [window, count, before, requestText, summary]() {
        if (aiChatState().value(QStringLiteral("busy")).toBool()) {
            window->showStatusMessage(QObject::tr("Your AI is still busy. Send again when it has answered."));
            return;
        }
        const int again = aiChatRequest(window, requestText, summary);
        if (!again) {
            window->showStatusMessage(QObject::tr("Your AI could not take the request. Menu > AI > Connect Your AI "
                                                  "checks it."));
            return;
        }
        showSentBanner(window, count, before, again, requestText, summary); // replaces this one
    });
    row->addWidget(resend);
    auto again = new QPushButton(QObject::tr("Review again"), banner);
    again->setObjectName(QStringLiteral("reviewBannerAgain"));
    again->hide();
    QObject::connect(again, &QPushButton::clicked, banner, [window, banner]() {
        banner->deleteLater();
        ReviewMode::show(window);
    });
    row->addWidget(again);
    auto dismiss = new QToolButton(banner);
    dismiss->setObjectName(QStringLiteral("reviewBannerClose"));
    dismiss->setText(QStringLiteral("✕"));
    dismiss->setToolTip(QObject::tr("Hide this"));
    dismiss->setAutoRaise(true);
    QObject::connect(dismiss, &QToolButton::clicked, banner, &QWidget::deleteLater);
    row->addWidget(dismiss);
    layout->insertWidget(0, banner);
    // this request's own outcome, once (a later message in the chat never reaches this banner)
    aiChatWatchRequest(banner, request, [banner, text, watch, resend, again, before](const QJsonObject &o) {
        const QString outcome = o.value("outcome").toString();
        QStringList changes;
        for (const auto &v : o.value("changes").toArray())
            changes << v.toString();
        QString answer = o.value("answer").toString().trimmed();
        if (answer.size() > 360)
            answer = answer.left(357) + QStringLiteral("...");
        const QString shownAnswer = answer.toHtmlEscaped().replace(QLatin1Char('\n'), QStringLiteral("<br>"));
        QString changeList = changes.mid(0, 4).join(QStringLiteral("; ")).toHtmlEscaped();
        if (changes.size() > 4)
            changeList += QObject::tr(" and %1 more").arg(changes.size() - 4);
        const QString tail = QObject::tr("<br><span style='color:%1'>The video before: “%2” in Versions of "
                                         "This Video. Undo takes back one change at a time.</span>")
                                 .arg(QString::fromLatin1(LetItEditColors::tealLight), before.toHtmlEscaped());
        QString headline;
        if (outcome == QLatin1String("answered")) {
            headline = changes.isEmpty() ? QObject::tr("<b>Your AI replied.</b> It made no changes to the video.")
                       : changes.size() == 1
                           ? QObject::tr("<b>Your AI made 1 change:</b> %1.").arg(changeList)
                           : QObject::tr("<b>Your AI made %1 changes:</b> %2.").arg(changes.size()).arg(changeList);
        } else {
            const QString why = outcome == QLatin1String("cancelled")
                                    ? QObject::tr("<b>Your AI was stopped before it finished.</b>")
                                    : QObject::tr("<b>Your AI couldn't finish:</b> %1")
                                          .arg(o.value("error").toString().left(200).toHtmlEscaped());
            headline = why + QLatin1Char(' ')
                       + (changes.isEmpty() ? QObject::tr("Nothing in the video was changed.")
                                            : QObject::tr("Before it stopped it made %1: %2.")
                                                  .arg(changes.size() == 1 ? QObject::tr("1 change")
                                                                           : QObject::tr("%1 changes").arg(changes.size()))
                                                  .arg(changeList));
        }
        text->setText(headline + (shownAnswer.isEmpty() ? QString() : QStringLiteral(" ") + shownAnswer)
                      + (changes.isEmpty() ? QString() : tail));
        watch->setVisible(!changes.isEmpty());
        resend->setVisible(outcome != QLatin1String("answered"));
        again->show();
        banner->setProperty("finished", true);
        banner->setProperty("outcome", outcome);
        banner->setProperty("changes", changes.size());
    });
}

// Where a project made from here goes: the app's own place for new projects, in a folder of its own as File > New makes
// it. Never beside the clip, which may be in the person's read-only originals. Empty when no folder can be chosen.
QString newProjectFile(const QString &name)
{
    QString home = qEnvironmentVariableIsSet("LETITEDIT_QA") ? qEnvironmentVariable("LETITEDIT_QA_PROJECTS_FOLDER")
                                                             : QString();
    if (home.isEmpty())
        home = Settings.projectsFolder();
    if (home.isEmpty())
        home = QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
    if (home.isEmpty())
        return QString();
    const QDir dir(home);
    for (int i = 1; i < 1000; ++i) {
        const QString folder = i == 1 ? name : QStringLiteral("%1 %2").arg(name).arg(i);
        if (!dir.exists(folder))
            return QDir::toNativeSeparators(dir.filePath(folder + QLatin1Char('/') + folder + QStringLiteral(".mlt")));
    }
    return QString();
}

bool timelineHasClips(MainWindow *window)
{
    if (!window->multitrack())
        return false;
    TimelineDock *timeline = window->timelineDock();
    for (int track = 0; track < timeline->model()->rowCount(); ++track)
        if (timeline->clipCount(track) > 0)
            return true;
    return false;
}

// Puts the clip in the player on the timeline, as Make a Short does (not TimelineDock::append, which takes what is on
// the clipboard if that is newer), and shows the timeline in the player.
bool putClipOnTimeline(MainWindow *window)
{
    if (!MLT.isSeekableClip())
        return false;
    Mlt::Playlist playlist(MLT.profile());
    playlist.append(*MLT.producer());
    window->player()->pause();
    window->timelineDock()->appendFromPlaylist(&playlist, false, false);
    if (!timelineHasClips(window))
        return false;
    window->seekTimeline(0);
    return true;
}

// Review needs a saved project with a timeline. When there isn't one the person still gets somewhere with one click: a
// line over the video says what's missing and offers the step that fixes it, which then opens Review. It holds up
// nothing (no dialog) and goes away when something else opens.
void showOpenOffer(MainWindow *window)
{
    using namespace LetItEditColors;
    auto layout = qobject_cast<QBoxLayout *>(window->player()->layout());
    const bool timeline = timelineHasClips(window);
    const bool clip = !timeline && MLT.isSeekableClip() && !MLT.isClosedClip();
    const QString current = window->fileName();
    const bool ownFile = clip && current.endsWith(QStringLiteral(".mlt"), Qt::CaseInsensitive)
                         && QFileInfo(current).isWritable();
    const QString clipFile = clip ? Util::GetFilenameFromProducer(MLT.producer()) : QString();
    QString name = QFileInfo(clipFile).completeBaseName();
    name.replace(QRegularExpression(QStringLiteral("[<>:\"/\\\\|?*]")), QStringLiteral(" "));
    name = name.trimmed();
    if (name.isEmpty())
        name = QObject::tr("My video");
    const QString target = ownFile ? current : newProjectFile(name);
    const QString shown = QDir::toNativeSeparators(QFileInfo(target).absolutePath()).toHtmlEscaped();
    const QString clipName = QFileInfo(clipFile).fileName().toHtmlEscaped();

    QString kind, words, action;
    if (timeline) {
        kind = QStringLiteral("timeline");
        words = QObject::tr("<b>Save this video first, so your AI can read it.</b> It goes in %1. File &gt; Save As "
                            "can move it later.")
                    .arg(shown);
        action = QObject::tr("Save and review");
    } else if (ownFile) {
        kind = QStringLiteral("saved-clip");
        words = QObject::tr("<b>This clip isn't on a timeline yet, and Review works on a timeline.</b> Put %1 on the "
                            "timeline of %2?")
                    .arg(clipName, QFileInfo(current).fileName().toHtmlEscaped());
        action = QObject::tr("Put it on the timeline and review");
    } else if (clip) {
        kind = QStringLiteral("clip");
        words = QObject::tr("<b>This is a clip, and Review works on a project.</b> Make a project from %1? It goes in "
                            "%2, and your clip stays where it is.")
                    .arg(clipName, shown);
        action = QObject::tr("Make a project and review");
    } else {
        kind = QStringLiteral("nothing");
        words = QObject::tr("<b>Nothing to review yet.</b> Open a video or a project, then Review it.");
        action = QObject::tr("Open a video or project");
    }
    if (!layout) {
        window->showStatusMessage(QTextDocumentFragment::fromHtml(words).toPlainText());
        return;
    }
    delete window->player()->findChild<QWidget *>(QStringLiteral("reviewOffer"));
    auto banner = new QWidget(window->player());
    banner->setObjectName(QStringLiteral("reviewOffer"));
    banner->setProperty("kind", kind);
    banner->setAttribute(Qt::WA_StyledBackground, true);
    banner->setStyleSheet(QStringLiteral("QWidget#reviewOffer { background: %1; border: 1px solid %2; border-radius: 10px; }"
                                         "QLabel#reviewOfferText { color: %3; font-size: 13px; }")
                              .arg(tealDeep, teal, cream));
    auto row = new QHBoxLayout(banner);
    row->setContentsMargins(14, 8, 10, 8);
    row->setSpacing(10);
    auto text = new QLabel(words, banner);
    text->setObjectName(QStringLiteral("reviewOfferText"));
    text->setWordWrap(true);
    row->addWidget(text, 1);
    auto go = new QPushButton(action, banner);
    go->setObjectName(QStringLiteral("reviewOfferGo"));
    go->setProperty("studioPrimary", true);
    row->addWidget(go);
    auto dismiss = new QToolButton(banner);
    dismiss->setObjectName(QStringLiteral("reviewOfferClose"));
    dismiss->setText(QStringLiteral("✕"));
    dismiss->setToolTip(QObject::tr("Hide this"));
    dismiss->setAutoRaise(true);
    QObject::connect(dismiss, &QToolButton::clicked, banner, &QWidget::deleteLater);
    row->addWidget(dismiss);
    layout->insertWidget(0, banner);

    // What this line offers stops being true when something else opens.
    QObject::connect(window, &MainWindow::producerOpened, banner, &QWidget::deleteLater);
    QObject::connect(go, &QPushButton::clicked, banner, [window, banner, text, go, kind, target]() {
        if (kind == QLatin1String("nothing")) {
            QMetaObject::invokeMethod(window, "openVideo", Qt::QueuedConnection);
            return;
        }
        const auto fail = [text](const QString &why) {
            text->setText(QObject::tr("<b>That didn't work:</b> %1 File &gt; Save As lets you choose another place.")
                              .arg(why.toHtmlEscaped()));
        };
        if (target.isEmpty()) {
            fail(QObject::tr("no folder for new projects was found."));
            return;
        }
        const QString folder = QFileInfo(target).absolutePath();
        if (!QDir().mkpath(folder)) {
            fail(QObject::tr("the folder %1 couldn't be made.").arg(folder));
            return;
        }
        if (kind != QLatin1String("timeline") && !putClipOnTimeline(window)) {
            fail(QObject::tr("the clip couldn't be put on a timeline."));
            return;
        }
        window->newProject(target, kind != QLatin1String("saved-clip"));
        if (QDir::fromNativeSeparators(window->fileName()) != QDir::fromNativeSeparators(target)) {
            fail(QObject::tr("the project couldn't be saved in %1.").arg(folder));
            return;
        }
        go->hide();
        text->setText(QObject::tr("<b>Saved:</b> %1").arg(QDir::toNativeSeparators(target).toHtmlEscaped()));
        banner->setProperty("kind", QStringLiteral("saved"));
        ReviewMode::show(window);
    });
}

QPointer<ReviewWindow> &openWindow()
{
    static QPointer<ReviewWindow> open;
    return open;
}

void show(MainWindow *window)
{
    auto &open = openWindow();
    if (open) {
        open->raise();
        open->activateWindow();
        return;
    }
    if (window->fileName().isEmpty() || !window->multitrack()) {
        showOpenOffer(window);
        return;
    }
    Timing &t = Timing::get();
    t.openStartNs = t.clock.nsecsElapsed();
    t.firstPaintNs = -1;
    t.openMs = -1;
    t.closeMs = -1;
    open = new ReviewWindow(window);
    // QA hook: LETITEDIT_QA_REVIEW_WINDOWED keeps a test window's Review in a window instead of over the whole screen
    if (qEnvironmentVariableIsSet("LETITEDIT_QA_REVIEW_WINDOWED")) {
        QSize size(1600, 900);
        const QStringList parts = qEnvironmentVariable("LETITEDIT_QA_REVIEW_SIZE").split(QLatin1Char('x'));
        if (parts.size() == 2 && parts[0].toInt() > 0 && parts[1].toInt() > 0)
            size = QSize(parts[0].toInt(), parts[1].toInt());
        open->resize(size);
        open->move(40, 40);
        open->show();
    } else if (QSettings(Settings.appDataLocation() + QStringLiteral("/review-talk-draw.ini"), QSettings::IniFormat)
                   .value(QStringLiteral("review/fullScreen"), false).toBool()) {
        open->showFullScreen(); // the person chose full screen last time (F, F11 or the button goes back)
    } else {
        open->showMaximized(); // a normal window (T210): full screen is one key away
    }
    open->activateWindow();
}

QJsonObject state()
{
    auto &open = openWindow();
    QJsonObject out = open ? open->state() : QJsonObject{{"open", false}, {"timing", Timing::get().json()}};
    if (auto banner = MAIN.player()->findChild<QWidget *>(QStringLiteral("liveReviewBanner"))) {
        auto text = banner->findChild<QLabel *>(QStringLiteral("liveReviewBannerText"));
        out["live_banner"] = text ? text->text() : QString();
    }
    if (!open)
        if (auto session = LiveReview::Session::existing(&MAIN))
            out["live_session"] = session->state();
    if (auto offer = MAIN.player()->findChild<QWidget *>(QStringLiteral("reviewOffer"))) {
        auto text = offer->findChild<QLabel *>(QStringLiteral("reviewOfferText"));
        auto go = offer->findChild<QPushButton *>(QStringLiteral("reviewOfferGo"));
        out["offer"] = QJsonObject{{"kind", offer->property("kind").toString()},
                                   {"text", text ? text->text() : QString()},
                                   {"button", go && !go->isHidden() ? go->text() : QString()}};
    }
    // the line over the video after sending: what it says and offers
    if (auto banner = MAIN.player()->findChild<QWidget *>(QStringLiteral("reviewBanner"))) {
        const auto visible = [banner](const char *name) {
            auto b = banner->findChild<QPushButton *>(QString::fromLatin1(name));
            return b && !b->isHidden();
        };
        auto text = banner->findChild<QLabel *>(QStringLiteral("reviewBannerText"));
        out["banner"] = QJsonObject{{"text", text ? text->text() : QString()},
                                    {"request", banner->property("request").toInt()},
                                    {"finished", banner->property("finished").toBool()},
                                    {"outcome", banner->property("outcome").toString()},
                                    {"changes", banner->property("changes").toInt()},
                                    {"watch", visible("reviewBannerWatch")},
                                    {"send_again", visible("reviewBannerResend")},
                                    {"mark_up_again", visible("reviewBannerAgain")}};
    }
    return out;
}

void installQaActions(MainWindow *window)
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        return;
    const auto add = [window](const QString &name, const std::function<void()> &run) {
        auto a = new QAction(name, window);
        window->addAction(a);
        Actions.add(name, a, QStringLiteral("QA"));
        QObject::connect(a, &QAction::triggered, window, run);
    };
    const QString out = Settings.appDataLocation() + QStringLiteral("/review-timing.json");
    // drawing over the playing video in a spoken take (needs LETITEDIT_QA_REVIEW_WAV for the voice)
    add(QStringLiteral("reviewQaDrawTalkAction"), [out]() {
        if (auto w = openWindow())
            w->qaDraw(true, qEnvironmentVariableIntValue("LETITEDIT_QA_DRAW_S") > 0 ? qEnvironmentVariableIntValue("LETITEDIT_QA_DRAW_S") : 6, out);
    });
    // drawing on a still frame
    add(QStringLiteral("reviewQaDrawStillAction"), [out]() {
        if (auto w = openWindow())
            w->qaDraw(false, qEnvironmentVariableIntValue("LETITEDIT_QA_DRAW_S") > 0 ? qEnvironmentVariableIntValue("LETITEDIT_QA_DRAW_S") : 4, out);
    });
    // Live Review: the next sound for the microphone's stand-in; its path is in the file LETITEDIT_QA_REVIEW_NEXT names
    add(QStringLiteral("reviewQaNextSoundAction"), []() {
        QFile f(qEnvironmentVariable("LETITEDIT_QA_REVIEW_NEXT"));
        if (auto w = openWindow(); w && f.open(QIODevice::ReadOnly))
            w->qaNextSound(QString::fromUtf8(f.readAll()).trimmed());
    });
    // the drawing and saving code as it was before (for a before/after measurement in one build)
    add(QStringLiteral("reviewQaLegacyAction"), []() { Timing::get().legacy = !Timing::get().legacy; });
}

} // namespace ReviewMode
