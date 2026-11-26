/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Export: letitedit's export panel, the studio export's preparation (code scenes, the guide song left out), its sound finish and its result.
 * (letitedit's additions to encodedock.cpp, moved out of Shotcut's file; the
 * declarations stay in its header.)
 */
#include "docks/encodedock.h"
#include "letitedit/dialogs/lejobs.h"
#include "letitedit/export/exportchecks.h"
#include "letitedit/export/othersizes.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/dialogs/problemreport.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "docks/timelinedock.h"
#include "models/subtitlesmodel.h"
#include "ui_encodedock.h"

#include "Logger.h"
#include "actions.h"
#include "dialogs/addencodepresetdialog.h"
#include "dialogs/listselectiondialog.h"
#include "dialogs/multifileexportdialog.h"
#include "docks/findanalysisfilterparser.h"
#include "gpuinfo.h"
#include "jobqueue.h"
#include "jobs/encodejob.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/markersmodel.h"
#include "qmltypes/qmlfilter.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"
#include "util.h"

#include <QFileInfo>
#include <QProcess>
#include <QRegularExpression>
#include <QRegularExpressionValidator>
#include <QTimer>
#include <QtMath>
#include <QtWidgets>
#include <QPlainTextEdit>
#include <QProgressBar>
#include <QHash>
#include <QSet>
#include <QtXml>

// The export snapshot is already a copy of the live timeline, including
// unsaved edits. Resolve every pinned scene there before the encoder sees it.
bool prepareCodeScenesForExport(QWidget *parent, const QString &snapshot,
                                       const QString &project)
{
    const QString python = aiChatSettings().value(QStringLiteral("python")).toString();
    const QString helper = aiRootPath(QStringLiteral("bridge/code_scenes.py"));
    if (!QFileInfo::exists(python) || !QFileInfo::exists(helper) || project.isEmpty()) {
        QMessageBox::warning(parent, QObject::tr("Export code scenes"),
                             QObject::tr("The scene renderer is missing. This export was stopped so the scenes "
                                         "cannot disappear from the video."));
        return false;
    }
    QProgressDialog progress(QObject::tr("Drawing code scenes for export…"), QString(), 0, 0, parent);
    progress.setCancelButton(nullptr);
    progress.setWindowModality(Qt::ApplicationModal);
    progress.setMinimumDuration(0);
    progress.show();
    QProcess process;
    process.setProcessChannelMode(QProcess::MergedChannels);
    process.setWorkingDirectory(QFileInfo(helper).absolutePath());
    process.start(python, {QStringLiteral("-u"), helper, QStringLiteral("--prepare-export"),
                           snapshot, project});
    if (!process.waitForStarted(10000)) {
        QMessageBox::warning(parent, QObject::tr("Export code scenes"),
                             QObject::tr("The scene renderer could not start. The export was stopped."));
        return false;
    }
    QByteArray output;
    QByteArray diagnostics;
    int done = -1;
    while (process.state() != QProcess::NotRunning) {
        process.waitForReadyRead(150);
        const QByteArray chunk = process.readAll();
        output += chunk;
        diagnostics += chunk;
        for (;;) {
            const int end = output.indexOf('\n');
            if (end < 0)
                break;
            const QByteArray line = output.left(end).trimmed();
            output.remove(0, end + 1);
            const QJsonObject event = QJsonDocument::fromJson(line).object();
            if (event.contains(QStringLiteral("index"))) {
                const int index = event.value(QStringLiteral("index")).toInt();
                const int total = event.value(QStringLiteral("total")).toInt();
                progress.setRange(0, qMax(1, total));
                progress.setValue(index - 1);
                progress.setLabelText(QObject::tr("Drawing scene %1 of %2 at full quality…")
                                          .arg(index).arg(total));
            } else if (event.contains(QStringLiteral("done"))) {
                done = event.value(QStringLiteral("done")).toInt();
            }
        }
        QCoreApplication::processEvents(QEventLoop::ExcludeUserInputEvents, 25);
    }
    output += process.readAll();
    diagnostics += output;
    if (done < 0) {
        for (const QByteArray &line : output.split('\n')) {
            const QJsonObject event = QJsonDocument::fromJson(line.trimmed()).object();
            if (event.contains(QStringLiteral("done")))
                done = event.value(QStringLiteral("done")).toInt();
        }
    }
    progress.close();
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0 || done < 0) {
        QMessageBox::warning(parent, QObject::tr("Export code scenes"),
                             QObject::tr("A scene could not be drawn at full quality. The export was stopped.\n\n%1")
                                 .arg(QString::fromUtf8(diagnostics).right(1200)));
        return false;
    }
    return true;
}

// T72: a track named "Song (not in the export)" holds a song the person adds in the phone app when posting. Every export leaves
// it out by that name, so a person who unmuted it to hear it can't put it in the upload. The track stays (mixes point at tracks by
// index), empty and hidden, and the song's producer goes, so the export never opens the file. bridge/guide_song.py does the same.
bool stripSongTrack(QDomDocument &dom)
{
    static const QRegularExpression name(QStringLiteral("^\\s*song \\(not in the export\\)"),
                                          QRegularExpression::CaseInsensitiveOption);
    QHash<QString, QDomElement> playlists;
    const QDomNodeList lists = dom.elementsByTagName(QStringLiteral("playlist"));
    for (int i = 0; i < lists.length(); ++i)
        playlists.insert(lists.item(i).toElement().attribute(QStringLiteral("id")), lists.item(i).toElement());
    bool stripped = false;
    QSet<QString> gone;
    const QDomNodeList tracks = dom.elementsByTagName(QStringLiteral("track"));
    for (int i = 0; i < tracks.length(); ++i) {
        QDomElement track = tracks.item(i).toElement();
        const auto found = playlists.constFind(track.attribute(QStringLiteral("producer")));
        if (found == playlists.constEnd())
            continue;
        QDomElement playlist = found.value();
        QString trackName;
        QList<QDomElement> items;
        for (QDomElement e = playlist.firstChildElement(); !e.isNull(); e = e.nextSiblingElement()) {
            if (e.tagName() == QLatin1String("property") && e.attribute(QStringLiteral("name")) == QLatin1String("shotcut:name"))
                trackName = e.text();
            else if (e.tagName() == QLatin1String("entry") || e.tagName() == QLatin1String("blank"))
                items.append(e);
        }
        if (!name.match(trackName).hasMatch())
            continue;
        track.setAttribute(QStringLiteral("hide"), QStringLiteral("both"));
        for (auto &item : items) {
            if (item.tagName() == QLatin1String("entry"))
                gone.insert(item.attribute(QStringLiteral("producer")));
            playlist.removeChild(item);
        }
        stripped = true;
    }
    if (!stripped)
        return false;
    const QDomNodeList entries = dom.elementsByTagName(QStringLiteral("entry"));
    for (int i = 0; i < entries.length(); ++i)
        gone.remove(entries.item(i).toElement().attribute(QStringLiteral("producer")));
    for (int i = 0; i < tracks.length(); ++i)
        gone.remove(tracks.item(i).toElement().attribute(QStringLiteral("producer")));
    for (const auto &tag : {QStringLiteral("producer"), QStringLiteral("chain")}) {
        QList<QDomElement> remove;
        const QDomNodeList nodes = dom.elementsByTagName(tag);
        for (int i = 0; i < nodes.length(); ++i)
            if (gone.contains(nodes.item(i).toElement().attribute(QStringLiteral("id"))))
                remove.append(nodes.item(i).toElement());
        for (auto &e : remove)
            e.parentNode().removeChild(e);
    }
    return true;
}

void EncodeDock::installStudioPresentation()
{
    if (m_studioQuality)
        return;
    auto legacy = widget();
    auto body = new QWidget(this);
    auto column = new QVBoxLayout(body);
    column->setContentsMargins(16, 14, 16, 16);
    column->setSpacing(12);
    auto pages = new QStackedWidget(body);
    auto simple = new QWidget(pages);
    auto form = new QVBoxLayout(simple);
    form->setContentsMargins(0, 0, 0, 0);
    form->setSpacing(14);
    buildStudioQuality(simple, form);
    // the extras are optional: a quiet toggle under the main action shows them
    auto extrasToggle = new QToolButton(body);
    extrasToggle->setObjectName(QStringLiteral("studioExportExtrasToggle"));
    extrasToggle->setText(tr("Chapters and shorts ▸"));
    extrasToggle->setCheckable(true);
    extrasToggle->setToolButtonStyle(Qt::ToolButtonTextOnly);
    auto extras = new QWidget(body);
    auto extrasColumn = new QVBoxLayout(extras);
    extrasColumn->setContentsMargins(0, 0, 0, 0);
    extrasColumn->setSpacing(8);
    extras->hide();
    connect(extrasToggle, &QToolButton::toggled, extras, [extras, extrasToggle](bool on) {
        extras->setVisible(on);
        extrasToggle->setText(on ? tr("Chapters and shorts ▾") : tr("Chapters and shorts ▸"));
    });
    auto chapters = new QPushButton(tr("YouTube chapters…"), simple);
    chapters->setObjectName(QStringLiteral("studioExportChapters"));
    chapters->setToolTip(tr("Chapter lines for the description, checked against YouTube's rules"));
    connect(chapters, &QPushButton::clicked, this, []() {
        if (auto a = Actions["youtubeChaptersAction"])
            a->trigger();
    });
    extrasColumn->addWidget(chapters);
    auto shorts = new QPushButton(tr("Make shorts from this video…"), simple);
    shorts->setObjectName(QStringLiteral("studioExportShorts"));
    shorts->setToolTip(tr("Your AI finds the moments that work on their own and makes each a vertical short"));
    connect(shorts, &QPushButton::clicked, this, []() {
        if (auto a = Actions["makeShortsFromLongAction"])
            a->trigger();
    });
    extrasColumn->addWidget(shorts);
    form->addStretch();
    auto save = new QPushButton(tr("Export video"), simple);
    save->setObjectName(QStringLiteral("studioExportStart"));
    save->setProperty("studioPrimary", true);
    form->addWidget(save);
    connect(save, &QPushButton::clicked, this, [this]() {
        // letitedit: the quick look (length, text under the apps' buttons, captions, gaps, first second) first.
        if (!ExportChecks::confirm(&MAIN, m_studioEvenVolume && m_studioEvenVolume->isChecked()))
            return;
        if (prepareStudioExport()) {
            m_studioRun = true;
            on_encodeButton_clicked();
            m_studioRun = false;
        }
    });
    m_studioSave = save;
    m_studioElsewhere = new QPushButton(tr("Save somewhere else…"), simple);
    m_studioElsewhere->setObjectName(QStringLiteral("studioExportElsewhere"));
    m_studioElsewhere->setFlat(true);
    form->addWidget(m_studioElsewhere);
    connect(m_studioElsewhere, &QPushButton::clicked, this, [this, save]() {
        m_chooseExportLocation = true;
        save->click();
        m_chooseExportLocation = false;
    });
    auto simplePage = new QScrollArea(pages);
    simplePage->setFrameShape(QFrame::NoFrame);
    simplePage->setWidgetResizable(true);
    simplePage->setWidget(simple);
    pages->addWidget(simplePage);
    auto advancedPage = new QScrollArea(pages);
    advancedPage->setFrameShape(QFrame::NoFrame);
    advancedPage->setWidgetResizable(true);
    advancedPage->setWidget(legacy);
    pages->addWidget(advancedPage);
    column->addWidget(pages, 1);
    column->addWidget(save);
    buildStudioRunStatus(body, column, save);
    column->addWidget(extrasToggle);
    column->addWidget(extras);
    auto more = new QToolButton(body);
    more->setText(tr("More export settings"));
    more->setCheckable(true);
    more->setToolButtonStyle(Qt::ToolButtonTextOnly);
    more->setObjectName(QStringLiteral("studioExportMore"));
    connect(more, &QToolButton::toggled, save, [save, extrasToggle, extras](bool advanced) {
        save->setVisible(!advanced);
        extrasToggle->setVisible(!advanced);
        extras->setVisible(!advanced && extrasToggle->isChecked());
    });
    connect(more, &QToolButton::toggled, this, [this, pages, more](bool advanced) {
        pages->setCurrentIndex(advanced ? 1 : 0);
        more->setText(advanced ? tr("← Simple export") : tr("More export settings"));
        // The complete native exporter remains available on explicit request.
        ui->advancedButton->setChecked(advanced);
        on_advancedButton_clicked(advanced);
    });
    column->addWidget(more);
    setWidget(body);
    auto moreAction = new QAction(tr("More export settings"), this);
    moreAction->setObjectName(QStringLiteral("studioExportMoreAction"));
    MAIN.addAction(moreAction);
    Actions.add(QStringLiteral("studioExportMoreAction"), moreAction, tr("Export"));
    connect(moreAction, &QAction::triggered, more, &QToolButton::click);
    installStudioQaActions();
}

void EncodeDock::buildStudioQuality(QWidget *simple, QVBoxLayout *form)
{
    auto title = new QLabel(tr("Ready to export"), simple);
    title->setProperty("studioHeading", true);
    form->addWidget(title);
    auto explanation = new QLabel(tr("Save your finished timeline as an MP4. It works on phones, computers and social platforms."), simple);
    explanation->setWordWrap(true);
    explanation->setProperty("studioMuted", true);
    form->addWidget(explanation);
    form->addWidget(new QLabel(tr("Quality"), simple));
    m_studioQuality = new QComboBox(simple);
    m_studioQuality->setObjectName(QStringLiteral("studioExportQuality"));
    m_studioQuality->addItems({tr("Recommended"), tr("Smaller file"), tr("Best quality")});
    form->addWidget(m_studioQuality);
    auto qualityHelp = new QLabel(tr("A clear picture without an unnecessarily large file."), simple);
    qualityHelp->setWordWrap(true);
    qualityHelp->setProperty("studioMuted", true);
    form->addWidget(qualityHelp);
    connect(m_studioQuality, &QComboBox::currentIndexChanged, qualityHelp, [qualityHelp](int index) {
        qualityHelp->setText(index == 1 ? tr("A smaller file for quicker uploads. Some detail is reduced.")
                               : index == 2 ? tr("Keep more detail. Takes more storage and longer to upload.")
                                            : tr("A clear picture without an unnecessarily large file."));
    });
    form->addWidget(new QLabel(tr("Video size"), simple));
    m_studioSize = new QComboBox(simple);
    m_studioSize->setObjectName(QStringLiteral("studioExportSize"));
    m_studioSize->addItems({tr("Same as project (recommended)"), tr("Up to 1080p"), tr("Up to 720p")});
    form->addWidget(m_studioSize);
    auto sizeHelp = new QLabel(tr("Keeps your video's shape and frame rate. Your timeline and source files are unchanged."), simple);
    sizeHelp->setWordWrap(true);
    sizeHelp->setProperty("studioMuted", true);
    form->addWidget(sizeHelp);
    m_studioEvenVolume = new QCheckBox(tr("Set the volume for YouTube and phones (recommended)"), simple);
    m_studioEvenVolume->setObjectName(QStringLiteral("studioExportEvenVolume"));
    m_studioEvenVolume->setChecked(true);
    m_studioEvenVolume->setToolTip(tr("After the export, the whole mix is raised or lowered evenly to the level "
                                      "YouTube, Shorts, TikTok and Reels play at (about -14 LUFS), with a safety limit so nothing "
                                      "gets too loud and crackles. Voice and music keep the balance you mixed; quiet moments stay quiet. "
                                      "Only the exported file changes, not your timeline."));
    form->addWidget(m_studioEvenVolume);
}

void EncodeDock::buildStudioRunStatus(QWidget *body, QVBoxLayout *column, QPushButton *save)
{
    // progress, the finished video, or what went wrong and how to fix it: right under the button
    m_studioRunBox = new QWidget(body);
    auto run = new QVBoxLayout(m_studioRunBox);
    run->setContentsMargins(0, 0, 0, 0);
    run->setSpacing(6);
    auto progressRow = new QHBoxLayout;
    m_studioProgress = new QProgressBar(m_studioRunBox);
    m_studioProgress->setObjectName(QStringLiteral("studioExportProgress"));
    m_studioProgress->setRange(0, 100);
    m_studioCancel = new QPushButton(tr("Cancel"), m_studioRunBox);
    m_studioCancel->setObjectName(QStringLiteral("studioExportCancel"));
    connect(m_studioCancel, &QPushButton::clicked, this, [this]() {
        if (auto run = static_cast<LeHeavyRun *>(m_studioFinishing))
            run->cancel();
        else if (m_studioJob)
            m_studioJob->stop();
    });
    progressRow->addWidget(m_studioProgress, 1);
    progressRow->addWidget(m_studioCancel);
    run->addLayout(progressRow);
    m_studioStatus = new QLabel(m_studioRunBox);
    m_studioStatus->setObjectName(QStringLiteral("studioExportStatus"));
    m_studioStatus->setWordWrap(true);
    m_studioStatus->setTextInteractionFlags(Qt::TextSelectableByMouse);
    run->addWidget(m_studioStatus);
    m_studioDone = new QWidget(m_studioRunBox);
    auto doneRow = new QHBoxLayout(m_studioDone);
    doneRow->setContentsMargins(0, 0, 0, 0);
    auto play = new QPushButton(tr("Play"), m_studioDone);
    play->setObjectName(QStringLiteral("studioExportPlay"));
    auto show = new QPushButton(tr("Show in folder"), m_studioDone);
    show->setObjectName(QStringLiteral("studioExportShow"));
    auto sizes = new QPushButton(tr("Other sizes…"), m_studioDone);
    sizes->setToolTip(tr("Copies in other shapes: vertical, square, portrait or wide"));
    connect(play, &QPushButton::clicked, this, [this]() { QDesktopServices::openUrl(QUrl::fromLocalFile(m_studioOutput)); });
    connect(show, &QPushButton::clicked, this, [this]() { Util::showInFolder(m_studioOutput); });
    connect(sizes, &QPushButton::clicked, this, [this]() { OtherSizes::show(&MAIN, m_studioOutput); });
    // letitedit: the quality gate on the finished file (Check my video), in plain words
    auto check = new QPushButton(tr("Check my video…"), m_studioDone);
    check->setObjectName(QStringLiteral("studioExportCheck"));
    check->setToolTip(tr("letitedit watches and listens to the finished video and says what to fix, in plain words"));
    connect(check, &QPushButton::clicked, this, [this]() { LeFeatures::showCheckVideo(&MAIN, m_studioOutput); });
    doneRow->addWidget(play);
    doneRow->addWidget(show);
    doneRow->addWidget(sizes);
    doneRow->addWidget(check);
    doneRow->addStretch();
    run->addWidget(m_studioDone);
    // the credit lines the video owes (Google's animated emoji, CC BY 4.0), with Copy for its description
    auto credits = new QWidget(m_studioRunBox);
    credits->setObjectName(QStringLiteral("studioExportCreditsBox"));
    auto creditsRow = new QHBoxLayout(credits);
    creditsRow->setContentsMargins(0, 4, 0, 0);
    auto creditsText = new QLabel(credits);
    creditsText->setObjectName(QStringLiteral("studioExportCredits"));
    creditsText->setWordWrap(true);
    creditsText->setTextInteractionFlags(Qt::TextSelectableByMouse);
    auto creditsCopy = new QPushButton(tr("Copy"), credits);
    creditsCopy->setObjectName(QStringLiteral("studioExportCreditsCopy"));
    creditsCopy->setToolTip(tr("Copy the credit line for the video's description"));
    connect(creditsCopy, &QPushButton::clicked, this, [credits, creditsCopy]() {
        QApplication::clipboard()->setText(credits->property("leCredits").toString());
        creditsCopy->setText(tr("Copied"));
    });
    creditsRow->addWidget(creditsText, 1);
    creditsRow->addWidget(creditsCopy, 0, Qt::AlignTop);
    credits->hide();
    run->addWidget(credits);
    m_studioFailed = new QWidget(m_studioRunBox);
    auto failRow = new QHBoxLayout(m_studioFailed);
    failRow->setContentsMargins(0, 0, 0, 0);
    auto retry = new QPushButton(tr("Try again…"), m_studioFailed);
    retry->setObjectName(QStringLiteral("studioExportRetry"));
    connect(retry, &QPushButton::clicked, save, &QPushButton::click);
    auto details = new QToolButton(m_studioFailed);
    details->setText(tr("Details"));
    details->setCheckable(true);
    // T368: what the failed export said (its line and the last lines of Details) goes into the report window
    auto report = new QToolButton(m_studioFailed);
    report->setObjectName(QStringLiteral("studioExportReport"));
    report->setText(tr("Report this problem"));
    connect(report, &QToolButton::clicked, this, [this]() {
        const QStringList details = m_studioLog->toPlainText().split(QLatin1Char('\n'));
        QString screen = m_studioStatus->text();
        if (!details.join(QString()).trimmed().isEmpty())
            screen += QStringLiteral("\nDetails:\n") + details.mid(qMax(0, int(details.size()) - 40)).join(QLatin1Char('\n'));
        ProblemReport::showDialog(&MAIN, ProblemReport::Context{QStringLiteral("export-error"), QStringLiteral("problem"), screen});
    });
    failRow->addWidget(retry);
    failRow->addWidget(details);
    failRow->addWidget(report);
    failRow->addStretch();
    run->addWidget(m_studioFailed);
    m_studioLog = new QPlainTextEdit(m_studioRunBox);
    m_studioLog->setReadOnly(true);
    m_studioLog->setMaximumHeight(120);
    m_studioLog->hide();
    connect(details, &QToolButton::toggled, m_studioLog, &QWidget::setVisible);
    run->addWidget(m_studioLog);
    m_studioRunBox->hide();
    column->addWidget(m_studioRunBox);
}

void EncodeDock::installStudioQaActions()
{
    if (qEnvironmentVariableIsSet("LETITEDIT_QA")) {
        for (bool render : {false, true}) {
            auto qa = new QAction(tr("Verify simple export"), this);
            const QString key = render ? QStringLiteral("studioQaExportAction") : QStringLiteral("studioQaPrepareExportAction");
            qa->setObjectName(key);
            MAIN.addAction(qa);
            Actions.add(key, qa, tr("UI verification"));
            connect(qa, &QAction::triggered, this, [this, render]() {
                if (!prepareStudioExport())
                    return;
                auto report = property("studioExportSettings").toMap();
                if (render) {
                    const QString root = qEnvironmentVariable("LETITEDIT_ROOT") + QStringLiteral("/tests/studio-ui-20261025");
                    QDir().mkpath(root);
                    const QString path = root + QStringLiteral("/native-export-%1.mp4").arg(QDateTime::currentMSecsSinceEpoch());
                    m_studioRun = true; // exactly what the Export button queues
                    enqueueAnalysis();
                    enqueueMelt({path}, -1);
                    m_studioRun = false;
                    report.insert(QStringLiteral("output"), path);
                }
                QFile file(Settings.appDataLocation() + QStringLiteral("/studio-export-settings.json"));
                if (file.open(QIODevice::WriteOnly))
                    file.write(QJsonDocument(QJsonObject::fromVariantMap(report)).toJson());
            });
        }
    }
}

bool EncodeDock::prepareStudioExport()
{
    if (!m_studioQuality || !MAIN.multitrack() || !MAIN.multitrack()->is_valid()) {
        MAIN.showStatusMessage(tr("Add clips to your timeline before exporting."));
        return false;
    }
    // Always export the edited timeline, even if a source clip is being previewed.
    const int from = ui->fromCombo->findData(QStringLiteral("timeline"));
    if (from < 0)
        return false;
    ui->fromCombo->setCurrentIndex(from);
    onProfileChanged();
    ui->hwencodeCheckBox->setChecked(false);
    Mlt::Properties preset;
    preset.set("f", "mp4");
    preset.set("vcodec", "libx264");
    preset.set("acodec", "aac");
    preset.set("crf", m_studioQuality->currentIndex() == 1 ? 26 : m_studioQuality->currentIndex() == 2 ? 18 : 21);
    preset.set("preset", "fast");
    preset.set("pix_fmt", "yuv420p");
    preset.set("ab", "192k");
    preset.set("ar", 48000);
    preset.set("channels", 2);
    preset.set("movflags", "+faststart");
    preset.set("meta.preset.extension", "mp4");
    loadPresetFromProperties(preset);
    int width = MLT.profile().width(), height = MLT.profile().height();
    const int limit = m_studioSize->currentIndex() == 1 ? 1920 : m_studioSize->currentIndex() == 2 ? 1280 : qMax(width, height);
    const double scale = qMin(1.0, double(limit) / qMax(width, height));
    width = qMax(2, qRound(width * scale / 2) * 2);
    height = qMax(2, qRound(height * scale / 2) * 2);
    ui->widthSpinner->setValue(width);
    ui->heightSpinner->setValue(height);
    ui->fpsSpinner->setValue(MLT.profile().fps());
    ui->dualPassCheckbox->setChecked(false);
    setProperty("studioExportSettings", QVariantMap{{"from", QStringLiteral("timeline")},
        {"format", ui->formatCombo->currentText()}, {"videoCodec", ui->videoCodecCombo->currentText()},
        {"audioCodec", ui->audioCodecCombo->currentText()}, {"width", width}, {"height", height},
        {"fps", ui->fpsSpinner->value()}, {"quality", m_studioQuality->currentText()}});
    return true;
}

void EncodeDock::studioStarted(AbstractJob *job, const QString &output)
{
    if (!m_studioRunBox)
        return;
    m_studioJob = job;
    m_studioOutput = output;
    m_studioRunBox->show();
    m_studioProgress->show();
    m_studioProgress->setValue(0);
    m_studioCancel->show();
    m_studioDone->hide();
    if (auto credits = findChild<QWidget *>(QStringLiteral("studioExportCreditsBox")))
        credits->hide();
    m_studioFailed->hide();
    m_studioLog->hide();
    m_studioStatus->setText(tr("Exporting to %1…").arg(QFileInfo(output).fileName()));
    m_studioEvenRun = m_studioEvenVolume && m_studioEvenVolume->isChecked();
    if (m_studioSave)
        m_studioSave->setEnabled(false);
    if (m_studioElsewhere)
        m_studioElsewhere->setEnabled(false);
    connect(job, &AbstractJob::lockWaiting, this, [this, job, output](const QString &words) {
        if (job != m_studioJob)
            return;
        m_studioStatus->setText(words.isEmpty() ? tr("Exporting to %1…").arg(QFileInfo(output).fileName())
                                                : words + QLatin1Char(' ') + tr("Your export starts when it is done."));
    });
    connect(job, &AbstractJob::progressUpdated, this, [this, job](QStandardItem *, int percent) {
        if (job != m_studioJob)
            return;
        m_studioProgress->setValue(percent);
        const QTime left = job->estimateRemaining(percent);
        m_studioStatus->setText(left.isValid() && percent > 2
                                    ? tr("Exporting… %1% (about %2 left)").arg(percent).arg(left.toString(QStringLiteral("m:ss")))
                                    : tr("Exporting… %1%").arg(percent));
    });
    connect(job, &AbstractJob::finished, this, [this](AbstractJob *j, bool isSuccess, QString) {
        studioFinished(j, isSuccess);
    });
}

void EncodeDock::studioFinished(AbstractJob *job, bool isSuccess)
{
    if (m_studioElsewhere && job == m_studioJob)
        m_studioElsewhere->setEnabled(true);
    if (!m_studioRunBox || job != m_studioJob)
        return;
    m_studioProgress->hide();
    m_studioCancel->hide();
    if (m_studioSave)
        m_studioSave->setEnabled(true);
    if (isSuccess) {
        finishStudioSound(); // then "ready", with the sound as measured on the file
        return;
    }
    const QString log = job->log();
    QString why;
    if (job->stopped())
        why = tr("Export canceled. Your video is unchanged.");
    else if (log.contains(QLatin1String("Permission denied"), Qt::CaseInsensitive))
        why = tr("letitedit couldn't save in that folder. Try again and choose another place, such as Videos or "
                 "the Desktop.");
    else if (log.contains(QLatin1String("No space left"), Qt::CaseInsensitive))
        why = tr("The disk is full. Free some space or choose another drive, then try again.");
    else if (log.contains(QLatin1String("No such file or directory"), Qt::CaseInsensitive))
        why = tr("That place isn't available (an unplugged drive or a moved folder?). Try again and choose "
                 "another place.");
    else
        why = tr("The export stopped before the end. Your project is unchanged. Try again; if it stops again, "
                 "Details shows why.");
    m_studioStatus->setText(why);
    m_studioLog->setPlainText(log.right(4000));
    m_studioFailed->show();
    if (!isVisible())
        MAIN.showStatusMessage(why, 15);
}

void EncodeDock::finishStudioSound()
{
    const QString python = aiChatSettings().value("python").toString();
    const QString script = aiRootPath(QStringLiteral("bridge/loudness_finish.py"));
    if (!QFileInfo::exists(python) || !QFileInfo::exists(script)) {
        showStudioReady(m_studioEvenRun ? tr("The volume could not be set (letitedit's tools are missing); the video is "
                                             "saved as it was mixed.")
                                        : QString());
        return;
    }
    m_studioProgress->setRange(0, 0); // working, no percentage
    m_studioProgress->show();
    m_studioCancel->show();
    if (m_studioElsewhere)
        m_studioElsewhere->setEnabled(false);
    if (m_studioSave)
        m_studioSave->setEnabled(false);
    const QString saved = m_studioEvenRun ? tr("Your video is saved. Now setting its volume for YouTube and phones and "
                                               "measuring it…")
                                          : tr("Your video is saved. Measuring its volume…");
    m_studioStatus->setText(saved);
    auto run = new LeHeavyRun(this);
    m_studioFinishing = run;
    QStringList args{QStringLiteral("-u"), script, QDir::toNativeSeparators(m_studioOutput)};
    if (m_studioEvenRun)
        args << QStringLiteral("--target") << QStringLiteral("-14") << QStringLiteral("--true-peak") << QStringLiteral("-1");
    else
        args << QStringLiteral("--measure-only");
    run->waiting = [this, saved](const QString &words) {
        m_studioStatus->setText(words.isEmpty() ? saved : words + QLatin1Char(' ') + tr("Your video is saved; its volume is set next."));
    };
    run->done = [this, run](bool ok, const QByteArray &out, const QByteArray &err) {
        run->deleteLater();
        m_studioFinishing = nullptr;
        m_studioProgress->setRange(0, 100);
        const QJsonObject r = QJsonDocument::fromJson(out.mid(out.indexOf('{'))).object();
        const QJsonObject after = r.value("after").toObject();
        QString line;
        if (!ok || r.isEmpty()) {
            QStringList lines = QString::fromUtf8(err).split(QLatin1Char('\n'), Qt::SkipEmptyParts);
            const QString why = lines.isEmpty() ? tr("stopped") : lines.last().trimmed().left(160);
            line = m_studioEvenRun ? tr("The volume was not set (%1); the video is saved as it was mixed.").arg(why)
                                   : QString();
            LOG_WARNING() << "export sound finishing failed:" << err.right(600);
        } else if (after.value("integrated_lufs").isNull()) {
            line = tr("It has no sound to measure.");
        } else {
            const double lufs = after.value("integrated_lufs").toDouble();
            const QString peak = after.value("true_peak_dbtp").isNull()
                                     ? QString()
                                     : tr(", peaks %1 dBTP").arg(after.value("true_peak_dbtp").toDouble(), 0, 'f', 1);
            if (r.value("changed").toBool()) {
                const double gain = r.value("gain_db").toDouble();
                line = tr("Volume measured on the file: %1 LUFS%2 (the whole mix %3 by %4 dB; voice and music keep "
                          "their balance).")
                           .arg(lufs, 0, 'f', 1)
                           .arg(peak)
                           .arg(gain >= 0 ? tr("raised") : tr("lowered"))
                           .arg(qAbs(gain), 0, 'f', 1);
            } else {
                line = m_studioEvenRun ? tr("Volume measured on the file: %1 LUFS%2.").arg(lufs, 0, 'f', 1).arg(peak)
                                       : tr("Volume measured on the file: %1 LUFS%2 (the volume setting was off).")
                                             .arg(lufs, 0, 'f', 1)
                                             .arg(peak);
            }
        }
        setProperty("studioSoundReport", QString::fromUtf8(QJsonDocument(r).toJson(QJsonDocument::Compact)));
        showStudioReady(line);
    };
    run->start(QStringLiteral("letitedit export: setting the volume of %1").arg(QFileInfo(m_studioOutput).fileName()),
               python, args);
}

void EncodeDock::showStudioReady(const QString &soundLine)
{
    if (m_studioElsewhere)
        m_studioElsewhere->setEnabled(true);
    m_studioProgress->hide();
    m_studioCancel->hide();
    if (m_studioSave)
        m_studioSave->setEnabled(true);
    const QString name = QFileInfo(m_studioOutput).fileName();
    const QString text = soundLine.isEmpty() ? tr("Export finished: %1").arg(name)
                                             : tr("Export finished: %1. %2").arg(name, soundLine);
    m_studioStatus->setText(text);
    m_studioDone->show();
    LeFeatures::rememberExport(m_studioOutput);
    if (auto credits = findChild<QWidget *>(QStringLiteral("studioExportCreditsBox"))) {
        const QJsonArray owed = LeFeatures::credits(&MAIN);
        const QString lines = LeFeatures::creditText(owed);
        credits->setProperty("leCredits", lines);
        if (auto label = credits->findChild<QLabel *>(QStringLiteral("studioExportCredits")))
            label->setText(tr("This video owes a credit line. Put it in the video's description:") + QLatin1Char('\n')
                           + lines);
        if (auto copy = credits->findChild<QPushButton *>(QStringLiteral("studioExportCreditsCopy")))
            copy->setText(tr("Copy"));
        credits->setVisible(!owed.isEmpty());
    }
    if (!isVisible())
        MAIN.showStatusMessage(text, 15);
}
