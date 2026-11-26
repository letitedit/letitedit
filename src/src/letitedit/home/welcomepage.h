/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The empty editor has one job: start a video. Progress replaces that invitation while the AI works.
 */
#ifndef WELCOMEPAGE_H
#define WELCOMEPAGE_H

#include "actions.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/dialogs/problemreport.h"
#include "mainwindow.h"
#include "letitedit/home/homevideos.h"
#include "letitedit/newvideo/learnlooks.h"
#include "letitedit/workspace/progressview.h"
#include "letitedit/workspace/progressstate.h"

#include <QtWidgets>

class WelcomePage : public QWidget
{
public:
    explicit WelcomePage(MainWindow *window, QWidget *parent)
        : QWidget(parent)
    {
        setObjectName(QStringLiteral("welcomePage"));
        auto *outer = new QVBoxLayout(this);
        outer->setContentsMargins(24, 12, 24, 12);
        outer->addStretch(1);

        auto *center = new QWidget(this);
        center->setMaximumWidth(610);
        auto *column = new QVBoxLayout(center);
        column->setAlignment(Qt::AlignCenter);
        column->setSpacing(16);

        auto *logo = new QLabel(center);
        logo->setPixmap(QIcon(QStringLiteral(":/icons/letitedit/letitedit_lockup_dark-bg.svg"))
                            .pixmap(QSize(240, 120)));
        logo->setAlignment(Qt::AlignCenter);
        column->addWidget(logo);

        m_newVideo = new QPushButton(tr("New video"), center);
        m_newVideo->setObjectName(QStringLiteral("welcomeFirstCut"));
        m_newVideo->setProperty("studioPrimary", true);
        m_newVideo->setMinimumHeight(54);
        m_newVideo->setCursor(Qt::PointingHandCursor);
        connect(m_newVideo, &QPushButton::clicked, this, []() {
            if (auto a = Actions["makeFirstCutAction"])
                a->trigger();
        });
        buildStoppedRun(window, center, column);

        buildRunOutcome(window, center, column);

        buildStartChoices(window, center, column);

        buildOpenChoices(window, center, column);

        m_videosTitle = new QLabel(tr("Your projects"), this);
        m_videosTitle->setObjectName(QStringLiteral("welcomeVideosTitle"));
        m_videosTitle->setStyleSheet(QStringLiteral("font-size:18px; font-weight:600;"));
        m_videos = new HomeVideos(this);

        buildProgress(center, column);

        outer->addWidget(center, 0, Qt::AlignHCenter);
        outer->addWidget(m_videosTitle);
        outer->addWidget(m_videos);
        outer->addStretch(1);
        m_progress->hide();
        watchRuns(window);
    }

    void refresh()
    {
        const QJsonObject state = aiChatState();
        const bool busy = state.value(QStringLiteral("busy")).toBool();
        const QString request = state.value(QStringLiteral("chat_id")).toString() + QLatin1Char(':')
                                + QString::number(state.value(QStringLiteral("request")).toInt());
        if (busy && request != m_request && state.value(QStringLiteral("request")).toInt() > 0) {
            m_request = request;
            // T193: a later turn of the same New video (the app's carry-on, Continue the edit, Carry on after Stop, the
            // wait for a usage limit) carries on its run: same record, same step, same time so far.
            const QString run = progressRunOf(state);
            const bool sameRun = run.startsWith(QStringLiteral("nv-")) && run == m_run;
            m_run = run;
            m_stopped = false;
            m_carryAsked = false;
            if (sameRun)
                carryOnRun(state);
        }
        if (busy && request == m_request && m_carriedOn != m_request) {
            recordRequestStart(state);
        } else if (!busy && m_wasBusy && !m_request.isEmpty()) {
            recordRequestEnd(state);
        }
        m_wasBusy = busy;
        const QJsonObject progress = progressRecord(busy ? progressRunOf(state) : m_run);   // this window's own run (T193)
        syncProgressWaiting(progress, state, aiChatSettings().value(QStringLiteral("python")).toString(),
                            aiRootPath(QStringLiteral("bridge/progress_feed.py")));
        const ProgressState display = progressState(progress, state, m_requestIsVideo);
        m_finishedReview->setText(progressFinishedText(progress));
        m_finishedReview->setVisible(!busy && !m_finishedReview->text().isEmpty());
        const bool anyAi = ConnectAi::anyAi();
        if (!MAIN.fileName().isEmpty())
            m_noVideo = false; // something is open now: this page's news is old
        m_noVideoBox->setVisible(!display.visible && m_noVideo && !m_stopped);
        if (m_stopped && !display.visible) {
            const QJsonArray projects = progress.value(QStringLiteral("projects")).toArray();
            const QString name = projects.isEmpty() ? QString() : QFileInfo(projects.last().toString()).completeBaseName();
            m_stoppedText->setText(tr("You stopped this video.") + QLatin1Char(' ')
                                   + (name.isEmpty() ? tr("Everything done so far stays in your project.")
                                                     : tr("Everything done so far stays in your project, \u201c%1\u201d.").arg(name))
                                   + QLatin1Char(' ') + tr("Carry on picks up where it stopped."));
        }
        m_stoppedBox->setVisible(!display.visible && m_stopped);
        // Try again is the one main action while it's showing.
        if (m_newVideo->property("studioPrimary").toBool() == m_noVideo) {
            m_newVideo->setProperty("studioPrimary", !m_noVideo);
            m_newVideo->setMinimumHeight(m_noVideo ? 0 : 54);
            m_newVideo->style()->unpolish(m_newVideo);
            m_newVideo->style()->polish(m_newVideo);
        }
        m_openVideo->setVisible(!display.visible && m_offerOpen);
        m_newVideo->setVisible(!display.visible && anyAi);
        m_learn->setVisible(!display.visible && anyAi);
        {
            const QString active = LearnLooks::activeJob();
            const QJsonObject job = active.isEmpty() ? QJsonObject() : LearnLooks::readJob(active);
            const QString named = job.value(QStringLiteral("name")).toString(); // empty until the AI has named the Look
            m_learning->setText(active.isEmpty()     ? QString()
                                : named.isEmpty()    ? tr("Learning your new Look: %1").arg(LearnLooks::progressLine(job))
                                                     : tr("Learning “%1”: %2").arg(named, LearnLooks::progressLine(job)));
            m_learning->setVisible(!display.visible && !active.isEmpty());
        }
        m_noAi->setVisible(!display.visible && !anyAi);
        m_connect->setVisible(!display.visible && !anyAi);
        m_open->setVisible(!display.visible);
        m_empty->setVisible(!display.visible);
        if (display.visible)
            m_emptyChoice->hide();
        if (!busy)
            m_videos->refresh();
        m_videos->setVisible(!display.visible && m_videos->count() > 0 && !m_noVideo);
        m_videosTitle->setVisible(!display.visible && m_videos->count() > 0 && !m_noVideo);
        m_progress->setVisible(display.visible);
        if (display.visible) {
            m_progressText->setText(display.label);
            const QString soFar = display.done.isEmpty() ? display.soFar : display.done + QStringLiteral("\n") + display.soFar;
            m_range->setText(soFar.trimmed());
            m_range->setVisible(!soFar.trimmed().isEmpty());
            m_soFar->setText(display.now);
            m_soFar->setVisible(!display.now.isEmpty());
            m_art->setVisible(!display.note); // a Review note has no steps to show (T221)
            m_art->setProgress(display.step / 6.0, display.step);
            m_overdue->hide();   // no estimate on show (T193)
            m_stopRow->setVisible(busy);
        }
    }

protected:
    void showEvent(QShowEvent *event) override
    {
        refresh();
        QWidget::showEvent(event);
    }

private:
    void buildStoppedRun(MainWindow *window, QWidget *center, QVBoxLayout *column)
    {
        // T193: a New video the person stopped (or that stopped before it was finished): what was kept, and Carry on, which
        // sends the chat's own Continue the edit (the same run, its finished work reused).
        m_stoppedBox = new QWidget(center);
        m_stoppedBox->setObjectName(QStringLiteral("welcomeStopped"));
        m_stoppedBox->setMinimumWidth(520);
        auto *stoppedColumn = new QVBoxLayout(m_stoppedBox);
        stoppedColumn->setContentsMargins(0, 0, 0, 0);
        stoppedColumn->setSpacing(10);
        m_stoppedText = new QLabel(m_stoppedBox);
        m_stoppedText->setObjectName(QStringLiteral("welcomeStoppedText"));
        m_stoppedText->setAlignment(Qt::AlignCenter);
        m_stoppedText->setWordWrap(true);
        m_stoppedText->setStyleSheet(QStringLiteral("font-size:17px;"));
        stoppedColumn->addWidget(m_stoppedText);
        m_carryOn = new QPushButton(tr("Carry on"), m_stoppedBox);
        m_carryOn->setObjectName(QStringLiteral("welcomeCarryOn"));
        m_carryOn->setProperty("studioPrimary", true);
        m_carryOn->setMinimumHeight(54);
        m_carryOn->setCursor(Qt::PointingHandCursor);
        connect(m_carryOn, &QPushButton::clicked, this, [this, window]() {
            if (aiChatCarryOn(window)) {
                m_carryAsked = true;
                m_stopped = false;
                refresh();
            } else {
                MAIN.showStatusMessage(tr("Your AI is busy; Carry on works once it has finished."), 8);
            }
        });
        stoppedColumn->addWidget(m_carryOn);
        m_stoppedBox->hide();
        column->addWidget(m_stoppedBox);
    }

    void buildRunOutcome(MainWindow *window, QWidget *center, QVBoxLayout *column)
    {
        // A run ended with nothing to show for it: says so, keeps the request, and can send it again. A reply ending isn't a
        // video existing, and nothing here reads the AI's words: only the outcome the chat reported and the files found.
        m_noVideoBox = new QWidget(center);
        m_noVideoBox->setObjectName(QStringLiteral("welcomeNoVideo"));
        m_noVideoBox->setMinimumWidth(520);
        auto *noVideoColumn = new QVBoxLayout(m_noVideoBox);
        noVideoColumn->setContentsMargins(0, 0, 0, 0);
        noVideoColumn->setSpacing(8);
        auto *noVideoTitle = new QLabel(tr("No video came from this request"), m_noVideoBox);
        noVideoTitle->setObjectName(QStringLiteral("welcomeNoVideoTitle"));
        noVideoTitle->setAlignment(Qt::AlignCenter);
        noVideoTitle->setStyleSheet(QStringLiteral("font-size:18px; font-weight:700;"));
        noVideoColumn->addWidget(noVideoTitle);
        m_noVideoText = new QLabel(m_noVideoBox);
        m_noVideoText->setObjectName(QStringLiteral("welcomeNoVideoText"));
        m_noVideoText->setAlignment(Qt::AlignCenter);
        m_noVideoText->setWordWrap(true);
        // this page lays out from size hints, which don't follow word wrap: room for the longest of these
        m_noVideoText->setMinimumHeight(m_noVideoText->fontMetrics().lineSpacing() * 5);
        m_noVideoText->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
        noVideoColumn->addWidget(m_noVideoText);
        m_tryAgain = new QPushButton(tr("Try again"), m_noVideoBox);
        m_tryAgain->setObjectName(QStringLiteral("welcomeTryAgain"));
        m_tryAgain->setProperty("studioPrimary", true);
        m_tryAgain->setMinimumHeight(54);
        m_tryAgain->setCursor(Qt::PointingHandCursor);
        connect(m_tryAgain, &QPushButton::clicked, this, [this]() { tryAgain(); });
        noVideoColumn->addWidget(m_tryAgain);
        auto *seeChat = new QPushButton(tr("See what the AI said"), m_noVideoBox);
        seeChat->setObjectName(QStringLiteral("welcomeSeeChat"));
        seeChat->setFlat(true);
        seeChat->setCursor(Qt::PointingHandCursor);
        connect(seeChat, &QPushButton::clicked, this, [window]() {
            if (auto *chat = window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
                chat->show();
                chat->raise();
            }
        });
        noVideoColumn->addWidget(seeChat);
        // T368: what this screen says goes into the report window as one more part (the person sees it all first)
        m_reportProblem = new QPushButton(tr("Report this problem"), m_noVideoBox);
        m_reportProblem->setObjectName(QStringLiteral("welcomeReportProblem"));
        m_reportProblem->setFlat(true);
        m_reportProblem->setCursor(Qt::PointingHandCursor);
        connect(m_reportProblem, &QPushButton::clicked, this, [this, window]() {
            ProblemReport::showDialog(window, ProblemReport::Context{QStringLiteral("welcome-error"), QStringLiteral("problem"),
                                                                     m_noVideoText->text()});
        });
        noVideoColumn->addWidget(m_reportProblem);
        m_noVideoBox->hide();
        column->addWidget(m_noVideoBox);
        // A run ended and nothing was opened, and the window can't tell which of what it made to open by itself.
        m_openVideo = new QPushButton(tr("Open your video"), center);
        m_openVideo->setObjectName(QStringLiteral("welcomeOpenVideo"));
        m_openVideo->setProperty("studioPrimary", true);
        m_openVideo->setMinimumHeight(54);
        m_openVideo->setCursor(Qt::PointingHandCursor);
        m_openVideo->hide();
        connect(m_openVideo, &QPushButton::clicked, this, [this]() { openFinishedVideo(); });
        column->addWidget(m_openVideo);
    }

    void buildStartChoices(MainWindow *window, QWidget *center, QVBoxLayout *column)
    {
        // the two ways in: a new video, or learning a Look from a video the person likes (T164)
        auto *ways = new QHBoxLayout;
        ways->setSpacing(12);
        m_newVideo->setMinimumWidth(230);
        ways->addWidget(m_newVideo, 1);
        m_learn = new QPushButton(tr("Learn from a video"), center);
        m_learn->setObjectName(QStringLiteral("welcomeLearn"));
        m_learn->setMinimumHeight(54);
        m_learn->setMinimumWidth(230);
        m_learn->setCursor(Qt::PointingHandCursor);
        m_learn->setToolTip(tr("Show letitedit one to three videos you like. It learns how they are made and keeps it as a Look of your own."));
        connect(m_learn, &QPushButton::clicked, this, [window]() { LearnLooks::showDialog(window); });
        ways->addWidget(m_learn, 1);
        column->addLayout(ways);
        // a quiet way in with no AI run: an empty project, Short or YouTube, opened with the chat ready
        m_empty = new QPushButton(tr("Start with an empty timeline"), center);
        m_empty->setObjectName(QStringLiteral("welcomeEmptyTimeline"));
        m_empty->setFlat(true);
        m_empty->setCursor(Qt::PointingHandCursor);
        // plain text, the way a link reads: no frame, muted, underlined on hover
        m_empty->setStyleSheet(QStringLiteral("QPushButton#welcomeEmptyTimeline { border: none; background: transparent; padding: 2px 4px; "
                                              "color: #AFA9A0; } QPushButton#welcomeEmptyTimeline:hover, "
                                              "QPushButton#welcomeEmptyTimeline:focus { color: #F4EFE6; text-decoration: underline; }"));
        m_empty->setToolTip(tr("Open the editor with an empty timeline and the chat ready. No AI run starts."));
        column->addWidget(m_empty, 0, Qt::AlignHCenter);
        m_emptyChoice = new QWidget(center);
        m_emptyChoice->setObjectName(QStringLiteral("welcomeEmptyChoice"));
        auto *emptyRow = new QHBoxLayout(m_emptyChoice);
        emptyRow->setContentsMargins(0, 0, 0, 0);
        emptyRow->setSpacing(8);
        auto *emptyAsk = new QLabel(tr("What shape?"), m_emptyChoice);
        emptyAsk->setProperty("studioMuted", true);
        emptyRow->addWidget(emptyAsk);
        const QList<QPair<QString, QString>> shapes{{QStringLiteral("short"), tr("Short (vertical)")},
                                                    {QStringLiteral("long"), tr("YouTube video (wide)")}};
        for (const auto &shape : shapes) {
            const QString kind = shape.first;
            auto *button = new QPushButton(shape.second, m_emptyChoice);
            button->setObjectName(QStringLiteral("welcomeEmpty_%1").arg(kind));
            button->setCursor(Qt::PointingHandCursor);
            connect(button, &QPushButton::clicked, this, [this, window, kind]() {
                m_emptyChoice->hide();
                window->openEditorWithClips(kind, {});
            });
            emptyRow->addWidget(button);
        }
        m_emptyChoice->hide();
        column->addWidget(m_emptyChoice, 0, Qt::AlignHCenter);
        connect(m_empty, &QPushButton::clicked, this, [this]() { m_emptyChoice->setVisible(!m_emptyChoice->isVisible()); });
        m_learning = new QLabel(center);
        m_learning->setObjectName(QStringLiteral("welcomeLearning"));
        m_learning->setAlignment(Qt::AlignCenter);
        m_learning->setWordWrap(true);
        m_learning->setProperty("studioMuted", true);
        m_learning->hide();
        column->addWidget(m_learning);
    }

    void buildOpenChoices(MainWindow *window, QWidget *center, QVBoxLayout *column)
    {
        // With no AI on this PC, the one next step takes its place.
        m_noAi = new QLabel(tr("To make a video, letitedit runs your own AI subscription. None is on this PC yet."), center);
        m_noAi->setObjectName(QStringLiteral("welcomeNoAi"));
        m_noAi->setAlignment(Qt::AlignCenter);
        m_noAi->setWordWrap(true);
        m_noAi->hide();
        column->addWidget(m_noAi);
        m_connect = new QPushButton(tr("Set up your AI"), center);
        m_connect->setObjectName(QStringLiteral("welcomeConnectAi"));
        m_connect->setProperty("studioPrimary", true);
        m_connect->setMinimumHeight(54);
        m_connect->setCursor(Qt::PointingHandCursor);
        m_connect->hide();
        connect(m_connect, &QPushButton::clicked, this, [window]() {
            if (auto a = window->findChild<QAction *>(QStringLiteral("connectAiAction")))
                a->trigger();
        });
        column->addWidget(m_connect);

        Settings.videoProjectsFolder();
        m_open = new QPushButton(tr("Open another…"), center);
        m_open->setObjectName(QStringLiteral("welcomeOpen"));
        m_open->setFlat(true);
        m_open->setCursor(Qt::PointingHandCursor);
        connect(m_open, &QPushButton::clicked, this, [window]() {
            auto *dialog = new QFileDialog(window, tr("Open another video"), Settings.videoProjectsFolder(),
                                          tr("Videos and projects (*.mlt *.xml *.mp4 *.mov *.mkv *.avi *.webm *.m4v *.mts *.m2ts);;All files (*)"));
            dialog->setObjectName(QStringLiteral("welcomeOpenDialog"));
            dialog->setOption(QFileDialog::DontUseNativeDialog);
            dialog->setFileMode(QFileDialog::ExistingFile);
            dialog->setAttribute(Qt::WA_DeleteOnClose);
            connect(dialog, &QFileDialog::fileSelected, window, &MainWindow::openHomeVideo);
            dialog->open();
        });
        column->addWidget(m_open);
    }

    void buildProgress(QWidget *center, QVBoxLayout *column)
    {
        m_progress = new QWidget(center);
        m_progress->setObjectName(QStringLiteral("welcomeProgress"));
        m_progress->setMinimumWidth(520);
        auto *progressColumn = new QVBoxLayout(m_progress);
        progressColumn->setContentsMargins(0, 0, 0, 0);
        progressColumn->setSpacing(12);
        auto *title = new QLabel(tr("Making your video"), m_progress);
        title->setObjectName(QStringLiteral("welcomeProgressTitle"));
        title->setAlignment(Qt::AlignCenter);
        title->setStyleSheet(QStringLiteral("font-size:24px; font-weight:700;"));
        progressColumn->addWidget(title);
        m_progressText = new QLabel(tr("Getting ready..."), m_progress);
        m_progressText->setObjectName(QStringLiteral("welcomeProgressText"));
        m_progressText->setAlignment(Qt::AlignCenter);
        m_progressText->setWordWrap(true);
        m_progressText->setStyleSheet(QStringLiteral("font-size:18px;"));
        progressColumn->addWidget(m_progressText);
        m_art = new ProgressView(m_progress);
        progressColumn->addWidget(m_art);
        m_range = new QLabel(m_progress);   // the time so far (T193: no time-left guess)
        m_range->setObjectName(QStringLiteral("welcomeProgressRange"));
        m_range->setAlignment(Qt::AlignCenter);
        m_range->setStyleSheet(QStringLiteral("color:#9ED6E2; font-size:16px; font-weight:600;"));
        progressColumn->addWidget(m_range);
        m_soFar = new QLabel(m_progress);
        m_soFar->setObjectName(QStringLiteral("welcomeProgressSoFar"));
        m_soFar->setAlignment(Qt::AlignCenter);
        m_soFar->setWordWrap(true);
        m_soFar->setProperty("studioMuted", true);
        progressColumn->addWidget(m_soFar);
        // Stop, in plain words: one line to confirm, then the same as the chat's Stop (T193)
        m_stopRow = new QWidget(m_progress);
        auto *stopLayout = new QHBoxLayout(m_stopRow);
        stopLayout->setContentsMargins(0, 4, 0, 0);
        stopLayout->addStretch(1);
        m_stopButton = new QPushButton(tr("Stop"), m_stopRow);
        m_stopButton->setObjectName(QStringLiteral("welcomeProgressStop"));
        m_stopButton->setCursor(Qt::PointingHandCursor);
        stopLayout->addWidget(m_stopButton);
        m_stopConfirm = new QLabel(tr("Stop making this video? Everything done so far stays in your project; you can carry on later."),
                                   m_stopRow);
        m_stopConfirm->setObjectName(QStringLiteral("welcomeProgressStopConfirm"));
        m_stopConfirm->setWordWrap(true);
        stopLayout->addWidget(m_stopConfirm, 1);
        m_stopYes = new QPushButton(tr("Stop it"), m_stopRow);
        m_stopYes->setObjectName(QStringLiteral("welcomeProgressStopYes"));
        stopLayout->addWidget(m_stopYes);
        m_stopNo = new QPushButton(tr("Keep going"), m_stopRow);
        m_stopNo->setObjectName(QStringLiteral("welcomeProgressStopNo"));
        stopLayout->addWidget(m_stopNo);
        stopLayout->addStretch(1);
        confirmStop(false);
        connect(m_stopButton, &QPushButton::clicked, this, [this]() { confirmStop(true); });
        connect(m_stopNo, &QPushButton::clicked, this, [this]() { confirmStop(false); });
        connect(m_stopYes, &QPushButton::clicked, this, [this]() {
            confirmStop(false);
            aiChatStopRun();
            refresh();
        });
        progressColumn->addWidget(m_stopRow);
        m_overdue = new QLabel(tr("A good edit can take a little longer. I'm still working on it."), m_progress);
        m_overdue->setObjectName(QStringLiteral("welcomeProgressOverdue"));
        m_overdue->setAlignment(Qt::AlignCenter);
        m_overdue->setWordWrap(true);
        m_overdue->hide();
        progressColumn->addWidget(m_overdue);
        column->addWidget(m_progress);
        m_finishedReview = new QLabel(center);
        m_finishedReview->setObjectName(QStringLiteral("welcomeFinishedReview"));
        m_finishedReview->setWordWrap(true);
        m_finishedReview->setAlignment(Qt::AlignCenter);
        m_finishedReview->setOpenExternalLinks(true);
        column->addWidget(m_finishedReview);
    }

    void watchRuns(MainWindow *window)
    {
        aiChatWatchBusy(this, [this](bool) { refresh(); });
        aiChatWatchStartRefused(this, [this](const QString &asked, const QString &line, const QString &why, bool carryOn) {
            startRefused(asked, line, why, carryOn);
        });
        auto *timer = new QTimer(this);
        timer->setInterval(700);
        connect(timer, &QTimer::timeout, this, [this]() {
            if (isVisible())
                refresh();
        });
        timer->start();
        // a New video that waited for its Look is sent once the Look is saved (whatever is open)
        auto *waiting = new QTimer(this);
        waiting->setInterval(2000);
        connect(waiting, &QTimer::timeout, this, [window]() { LearnLooks::tick(window); });
        waiting->start();
    }

    void recordRequestStart(const QJsonObject &state)
    {
        m_carriedOn = m_request;
        QJsonObject choice = state.value(QStringLiteral("choice")).toObject();
        QString detail, shortLine;
        const QJsonArray messages = state.value(QStringLiteral("messages")).toArray();
        for (int i = messages.size() - 1; i >= 0; --i) {
            const QJsonObject message = messages[i].toObject();
            if (message.value(QStringLiteral("kind")) == QLatin1String("user")) {
                shortLine = message.value(QStringLiteral("text")).toString();
                detail = message.value(QStringLiteral("detail")).toString(shortLine);
                break;
            }
        }
        QString source;
        // the two ways New video words it: the full request and Turbo's short one
        auto match = QRegularExpression(QStringLiteral("from the folder (.+?)(?: \\(use the letitedit skills| in Turbo mode\\.)"))
                         .match(detail);
        if (match.hasMatch())
            source = match.captured(1);
        else {
            match = QRegularExpression(QStringLiteral("from these files: (.+?)(?: \\(use the letitedit skills| in Turbo mode\\.)"))
                        .match(detail);
            if (match.hasMatch())
                source = match.captured(1).split(QLatin1Char(';')).first().trimmed();
        }
        QString kind = QStringLiteral("short");
        if (detail.contains(QStringLiteral("What to make: both:"), Qt::CaseInsensitive))
            kind = QStringLiteral("both");
        else if (detail.contains(QStringLiteral("What to make: a YouTube video"), Qt::CaseInsensitive))
            kind = QStringLiteral("long");
        else if (detail.contains(QStringLiteral("review"), Qt::CaseInsensitive)
                 && !detail.contains(QStringLiteral("Make a first cut"), Qt::CaseInsensitive))
            kind = QStringLiteral("review");
        QJsonArray selectedFiles;
        const auto selectedMatch = QRegularExpression(QStringLiteral("from these files: (.+?)(?: \\(use the letitedit skills| in Turbo mode\\.)"))
                                       .match(detail);
        if (selectedMatch.hasMatch()) {
            for (const auto &file : selectedMatch.captured(1).split(QLatin1Char(';'), Qt::SkipEmptyParts))
                selectedFiles.append(file.trimmed());
        }
        const QString saveIn = QRegularExpression(QStringLiteral("(?:^|\\n)Save video in: ([^\\r\\n]+)"))
                                   .match(detail).captured(1).trimmed();
        // T221: a Review note's card names the note (its first quoted words) and how many went
        QString noteWhat;
        int noteCount = 0;
        if (kind == QLatin1String("review")) {
            const QString notes = detail.section(QStringLiteral("\n\n"), 1);
            static const QRegularExpression numbered(QStringLiteral("(?:^|\\n)(\\d+)\\. "));
            for (auto it = numbered.globalMatch(notes); it.hasNext();)
                noteCount = qMax(noteCount, it.next().captured(1).toInt());
            noteWhat = QRegularExpression(QStringLiteral("\"([^\"]+)\"")).match(notes).captured(1).simplified();
        }
        // the open project goes with a note: Review's chat names no run, so its AI's edits find the card by it
        const QJsonArray noteProjects = kind == QLatin1String("review") && !MAIN.fileName().isEmpty()
                                            ? QJsonArray{MAIN.fileName()}
                                            : QJsonArray{};
        const QJsonObject meta{{QStringLiteral("request_id"), m_request},
                               {QStringLiteral("what"), noteWhat}, {QStringLiteral("notes"), noteCount},
                               {QStringLiteral("projects"), noteProjects},
                               {QStringLiteral("run"), m_run}, {QStringLiteral("folder"), saveIn},
                               {QStringLiteral("instance"), qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main"))},
                                {QStringLiteral("files"), selectedFiles},
                               {QStringLiteral("source"), source}, {QStringLiteral("kind"), kind},
                               {QStringLiteral("engine"), choice.value(QStringLiteral("engine"))},
                               {QStringLiteral("model"), choice.value(QStringLiteral("model"))},
                               {QStringLiteral("effort"), choice.value(QStringLiteral("effort"))},
                               // nothing measured to estimate these from: the card says the time left is unknown
                               {QStringLiteral("no_estimate"), detail.contains(QStringLiteral(" in Turbo mode."))
                                                                   || detail.contains(QStringLiteral("Make a first cut with no footage"))}};
        m_requestIsVideo = detail.contains(QStringLiteral("Make a first cut"), Qt::CaseInsensitive)
                           || kind == QLatin1String("review");
        m_requestMakesVideo = detail.contains(QStringLiteral("Make a first cut"), Qt::CaseInsensitive);
        m_requestSource = source;
        m_requestFolder = saveIn;
        m_requestStarted = QDateTime::currentSecsSinceEpoch() - 5;
        m_finishedVideos.clear();
        m_offerOpen = false;
        m_noVideo = false;
        if (m_requestMakesVideo) {
            m_askedFor = detail;
            m_askedForLine = shortLine;
            m_endedWith.clear();
        }
        if (m_requestIsVideo)
            QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(),
                                    {aiRootPath(QStringLiteral("bridge/progress_feed.py")), QStringLiteral("start"),
                                     QStringLiteral("--json"), QString::fromUtf8(QJsonDocument(meta).toJson(QJsonDocument::Compact))});
    }

    void recordRequestEnd(const QJsonObject &state)
    {
        QJsonObject meta{{QStringLiteral("request_id"), m_request}, {QStringLiteral("run"), m_run}};
        QStringList args{aiRootPath(QStringLiteral("bridge/progress_feed.py")), QStringLiteral("finish"),
                         QStringLiteral("--json"), QString::fromUtf8(QJsonDocument(meta).toJson(QJsonDocument::Compact)),
                         QStringLiteral("--outcome"), QStringLiteral("failed")};
        const QJsonArray outcomes = state.value(QStringLiteral("outcomes")).toArray();
        const int endedRequest = m_request.section(QLatin1Char(':'), -1).toInt();
        for (const QJsonValue &value : outcomes) {
            const QJsonObject outcome = value.toObject();
            if (outcome.value(QStringLiteral("id")).toInt() != endedRequest)
                continue;
            const QString result = outcome.value(QStringLiteral("outcome")).toString();
            args.last() = result == QLatin1String("answered") ? QStringLiteral("done")
                          : result == QLatin1String("cancelled") ? QStringLiteral("stopped")
                          : QStringLiteral("failed");
            m_endedWith = outcome.value(QStringLiteral("error")).toString();
            break;
        }
        // T193: Stop also stops the exports the run started (and gives the PC lock back). A run letitedit gave up
        // carrying on is recorded as stopped, but Home treats it as before: its video opens, or it says none came.
        const QString ended = args.last();
        if (args.last() == QLatin1String("stopped"))
            args[1] = QStringLiteral("stop");
        else if (args.last() == QLatin1String("done") && state.value(QStringLiteral("new_video_stopped")).toBool())
            args.last() = QStringLiteral("stopped");
        m_stopped = args[1] == QLatin1String("stop") && m_requestMakesVideo && m_run.startsWith(QStringLiteral("nv-"));
        QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(), args);
        if (m_requestMakesVideo)
            findFinishedVideo(m_request, ended);
        m_requestMakesVideo = false;
        m_request.clear();
    }

    void confirmStop(bool on)
    {
        m_stopButton->setVisible(!on);
        m_stopConfirm->setVisible(on);
        m_stopYes->setVisible(on);
        m_stopNo->setVisible(on);
    }

    // A later turn of the run on show: its record carries on (bridge/progress_feed.py start keeps the step and the time)
    void carryOnRun(const QJsonObject &state)
    {
        m_carriedOn = m_request;
        m_requestIsVideo = m_requestMakesVideo = true;
        m_requestStarted = QDateTime::currentSecsSinceEpoch() - 5;
        m_finishedVideos.clear();
        m_offerOpen = false;
        m_noVideo = false;
        const QJsonObject choice = state.value(QStringLiteral("choice")).toObject();
        const QJsonObject meta{{QStringLiteral("run"), m_run}, {QStringLiteral("request_id"), m_request},
                               {QStringLiteral("engine"), choice.value(QStringLiteral("engine"))},
                               {QStringLiteral("model"), choice.value(QStringLiteral("model"))},
                               {QStringLiteral("effort"), choice.value(QStringLiteral("effort"))}};
        QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(),
                                {aiRootPath(QStringLiteral("bridge/progress_feed.py")), QStringLiteral("start"),
                                 QStringLiteral("--json"), QString::fromUtf8(QJsonDocument(meta).toJson(QJsonDocument::Compact))});
    }

    // A New video run has ended. If the AI opened nothing, this window opens what the run made: the run's own journal
    // says which project that is (bridge/first_cut_result.py), never a guess from a file's name.
    void findFinishedVideo(const QString &request, const QString &outcome)
    {
        const QJsonObject meta{{QStringLiteral("source"), m_requestSource},
                               {QStringLiteral("output"), m_requestFolder},
                               {QStringLiteral("since"), double(m_requestStarted)},
                               {QStringLiteral("request_id"), request}};
        auto *process = new QProcess(this);
        connect(process, &QProcess::finished, this, [this, process, outcome](int exitCode) {
            const QJsonObject found = exitCode == 0 ? QJsonDocument::fromJson(process->readAllStandardOutput()).object()
                                                    : QJsonObject();
            process->deleteLater();
            useFinishedVideo(found, outcome);
        });
        process->start(aiChatSettings().value(QStringLiteral("python")).toString(),
                       {aiRootPath(QStringLiteral("bridge/first_cut_result.py")), QStringLiteral("--json"),
                        QString::fromUtf8(QJsonDocument(meta).toJson(QJsonDocument::Compact))});
    }

    void useFinishedVideo(const QJsonObject &found, const QString &outcome)
    {
        // The AI opened it, or the person opened or started something: their window stays as it is.
        if (!MAIN.fileName().isEmpty() || MAIN.isWindowModified())
            return;
        if (!found.value(QStringLiteral("already_open")).toString().isEmpty()) {
            MAIN.showStatusMessage(tr("Your video is open in another letitedit window."), 15);
            return;
        }
        m_finishedVideos.clear();
        m_endOutcome = outcome;
        const QString project = found.value(QStringLiteral("project")).toString();
        if (!project.isEmpty()) {
            if (outcome == QLatin1String("done") && !QApplication::activeModalWidget()) {
                // Nobody clicked anything: this must not take the keyboard from whatever the person is doing.
                QMetaObject::invokeMethod(&MAIN, [project]() { MAIN.openWithoutFocus(project); }, Qt::QueuedConnection);
                return;
            }
            m_finishedVideos << project;
        } else {
            for (const QJsonValue &value : found.value(QStringLiteral("candidates")).toArray())
                m_finishedVideos << value.toString();
        }
        settleFinishedVideos();
    }

    // Only what is really there is offered. Nothing there: say so.
    void settleFinishedVideos()
    {
        QStringList there;
        for (const QString &path : std::as_const(m_finishedVideos))
            if (QFileInfo(path).isFile())
                there << path;
        m_finishedVideos = there;
        m_offerOpen = !there.isEmpty();
        m_noVideo = there.isEmpty();
        if (m_noVideo) {
            const QString what = m_endOutcome == QLatin1String("done") ? tr("Your AI finished, but letitedit can't find a video from this request.")
                                 : m_endOutcome == QLatin1String("stopped") ? tr("This request was stopped, and letitedit can't find a video from it.")
                                 : m_endedWith.isEmpty() ? tr("This request stopped with an error, and letitedit can't find a video from it.")
                                                         : tr("This request stopped with an error, and letitedit can't find a video from it: %1").arg(m_endedWith);
            m_noVideoText->setText(what + QLatin1Char(' ')
                                   + (m_askedFor.isEmpty() ? tr("If a video was saved somewhere, Open an existing video finds it.")
                                                           : tr("Your request is kept: Try again sends it as it was. If a video was saved "
                                                                "somewhere, Open an existing video finds it.")));
            m_tryAgain->setVisible(!m_askedFor.isEmpty());
            m_reportProblem->setVisible(m_endOutcome != QLatin1String("stopped"));
        }
        refresh();
    }

    void tryAgain()
    {
        if (m_askedFor.isEmpty())
            return;
        if (aiChatRequest(&MAIN, m_askedFor, m_askedForLine, false, true)) {
            m_noVideo = false;
            refresh();
        } else {
            m_noVideoText->setText(notTakenWords(aiChatRefusal()));
        }
    }

    static QString notTakenWords(const QString &why)
    {
        return !why.isEmpty() ? why : tr("Your AI couldn't take the request just now. Try again in a moment: it's still kept.");
    }

    // A start the chat answered with an id (so New video, Try again or Carry on took it as sent) was refused
    // afterwards. No busy turn tells this page, so the chat does: it shows what it shows when a send is refused at once.
    void startRefused(const QString &asked, const QString &line, const QString &why, bool carryOn)
    {
        if (carryOn) {
            m_stopped = m_stopped || m_carryAsked; // Carry on hid the stopped video's box: it comes back
        } else {
            m_askedFor = asked;
            m_askedForLine = line;
            m_run.clear(); // an earlier run's "ready" line is not this request's
            m_stopped = false;
            m_offerOpen = false;
            m_finishedVideos.clear();
            m_noVideo = true;
            m_noVideoText->setText(notTakenWords(why));
            m_tryAgain->setVisible(true);
            m_reportProblem->setVisible(true);
        }
        m_carryAsked = false;
        refresh();
    }

    void openFinishedVideo()
    {
        settleFinishedVideos(); // moved or deleted since it was offered
        if (m_finishedVideos.size() == 1) {
            openLater(m_finishedVideos.first());
        } else if (m_finishedVideos.size() > 1) {
            auto *menu = new QMenu(m_openVideo);
            menu->setObjectName(QStringLiteral("welcomeOpenVideoMenu"));
            menu->setAttribute(Qt::WA_DeleteOnClose);
            for (const QString &path : std::as_const(m_finishedVideos))
                menu->addAction(QFileInfo(path).completeBaseName(), this, [path]() { openLater(path); });
            menu->popup(m_openVideo->mapToGlobal(QPoint(0, m_openVideo->height())));
        }
    }

    // The person's own click: the window comes forward as for any open. Queued, as the tool bridge does: opening a
    // project from inside a click or a closing menu pulls this page away from under the event it is still handling.
    static void openLater(const QString &path)
    {
        QMetaObject::invokeMethod(&MAIN, [path]() { MAIN.openMultiple(QStringList{path}); }, Qt::QueuedConnection);
    }

    QPushButton *m_openVideo{nullptr};
    QWidget *m_stoppedBox{nullptr};
    QLabel *m_stoppedText{nullptr};
    QPushButton *m_carryOn{nullptr};
    QWidget *m_stopRow{nullptr};
    QPushButton *m_stopButton{nullptr};
    QLabel *m_stopConfirm{nullptr};
    QPushButton *m_stopYes{nullptr};
    QPushButton *m_stopNo{nullptr};
    bool m_stopped{false};
    bool m_carryAsked{false}; // Carry on was pressed here and no turn has begun for it yet
    QString m_run;          // the run this window's card shows (progress_feed's runs/<run>.json)
    QString m_carriedOn;    // the request whose start (or carry-on) was already sent
    QWidget *m_noVideoBox{nullptr};
    QLabel *m_noVideoText{nullptr};
    QPushButton *m_tryAgain{nullptr};
    QPushButton *m_reportProblem{nullptr};
    bool m_noVideo{false};
    QString m_askedFor;     // the whole request, as it was sent, for Try again
    QString m_askedForLine; // the chat's short line for it
    QString m_endedWith;    // the error the chat reported when it ended
    QString m_endOutcome;
    QLabel *m_soFar{nullptr};
    bool m_offerOpen{false};
    bool m_requestMakesVideo{false};
    QString m_requestSource;
    QString m_requestFolder;
    HomeVideos *m_videos{nullptr};
    QLabel *m_videosTitle{nullptr};
    qint64 m_requestStarted{0};
    QStringList m_finishedVideos;
    QPushButton *m_newVideo{nullptr};
    QPushButton *m_learn{nullptr};
    QPushButton *m_empty{nullptr};
    QWidget *m_emptyChoice{nullptr};
    QLabel *m_learning{nullptr};
    QLabel *m_noAi{nullptr};
    QPushButton *m_connect{nullptr};
    QPushButton *m_open{nullptr};
    QWidget *m_progress{nullptr};
    bool m_requestIsVideo{false};
    QLabel *m_progressText{nullptr};
    QLabel *m_finishedReview{nullptr};
    QLabel *m_range{nullptr};
    QLabel *m_overdue{nullptr};
    ProgressView *m_art{nullptr};
    QString m_request;
    bool m_wasBusy{false};
};

#endif // WELCOMEPAGE_H
