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

// Check my video: the export checked before it is posted.
// (Split out of lefeatures.cpp; what it shares with it is in featurehelpers.h.)

#include "featurehelpers.h"

namespace LeFeatures {

namespace {

class CheckVideoDialog : public QDialog
{
public:
    CheckVideoDialog(MainWindow *window, const QString &video)
        : QDialog(window)
        , m_window(window)
    {
        setObjectName(QStringLiteral("checkVideoDialog"));
        setWindowTitle(tr("Check my video"));
        setMinimumSize(700, 560);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        column->addWidget(headingLabel(tr("Check my video"), this));
        column->addWidget(mutedLabel(tr("letitedit watches and listens to the whole exported video on this computer and "
                                        "checks it for this kind of video: the length and size, the first seconds, how "
                                        "loud it is, silences, captions and pace. About a minute. Nothing is "
                                        "uploaded."),
                                     this));
        auto row = new QHBoxLayout;
        m_video = new QLineEdit(this);
        m_video->setObjectName(QStringLiteral("checkVideoFile"));
        m_video->setAccessibleName(tr("The video to check"));
        m_video->setPlaceholderText(tr("The exported video (export it first)"));
        m_video->setText(nativePath(video));
        auto choose = new QPushButton(tr("Choose..."), this);
        choose->setObjectName(QStringLiteral("checkVideoChoose"));
        connect(choose, &QPushButton::clicked, this, [this]() {
            const QString chosen = QFileDialog::getOpenFileName(
                this, tr("Video to check"), m_video->text().isEmpty() ? Settings.savePath() : m_video->text(),
                tr("Videos (%1)").arg(kVideoFiles.join(QLatin1Char(' '))), nullptr, Util::getFileDialogOptions());
            if (!chosen.isEmpty())
                m_video->setText(nativePath(chosen));
        });
        row->addWidget(m_video, 1);
        row->addWidget(choose);
        column->addLayout(row);
        m_run = new RunBox(this, QStringLiteral("checkVideo"));
        column->addWidget(m_run);
        m_result = new QTextBrowser(this);
        m_result->setObjectName(QStringLiteral("checkVideoResult"));
        m_result->setOpenLinks(false);
        m_result->hide();
        connect(m_result, &QTextBrowser::anchorClicked, this, [this](const QUrl &url) {
            if (url.scheme() == QLatin1String("copy")) {
                QApplication::clipboard()->setText(creditText(m_credits));
                m_run->say(tr("Copied. Paste it into your video's description."));
            }
        });
        column->addWidget(m_result, 1);
        auto buttons = new QHBoxLayout;
        auto close = new QPushButton(tr("Close"), this);
        close->setObjectName(QStringLiteral("checkVideoClose"));
        connect(close, &QPushButton::clicked, this, &QDialog::reject);
        m_stop = new QPushButton(tr("Stop"), this);
        m_stop->setObjectName(QStringLiteral("checkVideoStop"));
        m_stop->hide();
        connect(m_stop, &QPushButton::clicked, this, [this]() { m_run->run->cancel(); });
        m_report = new QPushButton(tr("Open the full report"), this);
        m_report->setObjectName(QStringLiteral("checkVideoReport"));
        m_report->hide();
        connect(m_report, &QPushButton::clicked, this, [this]() { QDesktopServices::openUrl(QUrl::fromLocalFile(m_reportFile)); });
        m_askAi = new QPushButton(tr("Ask my AI for a second opinion"), this);
        m_askAi->setObjectName(QStringLiteral("checkVideoAskAi"));
        m_askAi->setToolTip(tr("Your AI watches the pages of frames and the excerpts, judges story, pacing and shots, "
                               "and tells you what to fix first. It changes nothing."));
        m_askAi->hide();
        connect(m_askAi, &QPushButton::clicked, this, [this]() { askAi(); });
        m_go = new QPushButton(tr("Check it"), this);
        m_go->setObjectName(QStringLiteral("checkVideoGo"));
        m_go->setProperty("studioPrimary", true);
        m_go->setDefault(true);
        connect(m_go, &QPushButton::clicked, this, [this]() { go(); });
        buttons->addWidget(close);
        buttons->addStretch(1);
        buttons->addWidget(m_stop);
        buttons->addWidget(m_report);
        buttons->addWidget(m_askAi);
        buttons->addWidget(m_go);
        column->addLayout(buttons);
        m_run->done = [this](bool ok, const QJsonObject &result, const QString &why) { finished(ok, result, why); };
        if (video.isEmpty())
            m_run->say(tr("Export your video first, then check it here (or choose a video you exported before)."));
    }

    void reject() override
    {
        if (m_run->running())
            m_run->run->cancel();
        QDialog::reject();
    }

    QJsonObject qaState() const
    {
        return QJsonObject{{"visible", isVisible()}, {"running", m_run->running()}, {"status", m_run->status->text()},
                           {"video", m_video->text()}, {"verdict", m_verdict},
                           {"result", m_result->isVisible() ? m_result->toPlainText() : QString()},
                           {"ask_ai", m_askAi->isVisible()}};
    }

private:
    void go()
    {
        const QString video = m_video->text().trimmed();
        if (video.isEmpty() || !QFileInfo(video).isFile()) {
            m_run->say(tr("Choose the exported video first (Export makes one)."), true);
            return;
        }
        QStringList args{QStringLiteral("--video"), video};
        if (!m_window->fileName().isEmpty())
            args << QStringLiteral("--project") << m_window->fileName();
        m_go->setEnabled(false);
        m_stop->show();
        m_result->hide();
        m_run->start(QStringLiteral("check"), args, true, QStringLiteral("letitedit check my video"),
                     tr("Looking at the whole video and listening to it..."));
    }

    void finished(bool ok, const QJsonObject &result, const QString &why)
    {
        m_go->setEnabled(true);
        m_stop->hide();
        if (!ok) {
            m_run->say(why.isEmpty() ? tr("Stopped.") : tr("The check couldn't run: %1").arg(why), !why.isEmpty());
            return;
        }
        using namespace LetItEditColors;
        m_verdict = result.value("verdict").toString();
        m_reportFile = result.value("report").toString();
        m_credits = result.value("credits").toArray();
        const QJsonObject counts = result.value("counts").toObject();
        const QString colour = m_verdict == QLatin1String("ready")     ? QString::fromLatin1(ok_colour())
                               : m_verdict == QLatin1String("blocked") ? QStringLiteral("#ff8a80")
                               : m_verdict == QLatin1String("revise")  ? QStringLiteral("#ffb347")
                                                                       : QString::fromLatin1(tealLight);
        QString html = QStringLiteral("<p style='font-size:16px; font-weight:700; color:%1'>%2</p>")
                           .arg(colour, result.value("words").toString().toHtmlEscaped());
        const QJsonArray findings = result.value("findings").toArray();
        if (findings.isEmpty()) {
            html += QStringLiteral("<p>%1</p>").arg(tr("No problems found by the checks that ran.").toHtmlEscaped());
        } else {
            html += QStringLiteral("<p><b>%1</b></p><ul>")
                        .arg(tr("%1 serious, %2 worth fixing, %3 small")
                                 .arg(counts.value("critical").toInt())
                                 .arg(counts.value("major").toInt())
                                 .arg(counts.value("minor").toInt())
                                 .toHtmlEscaped());
            for (const auto &v : findings) {
                const QJsonObject f = v.toObject();
                const QString when = f.value("at").toString();
                const QString sev = f.value("severity").toString();
                const QString sevWords = sev == QLatin1String("critical") ? tr("serious")
                                         : sev == QLatin1String("major")  ? tr("worth fixing")
                                                                          : tr("small");
                html += QStringLiteral("<li><b>%1</b>%2: %3%4</li>")
                            .arg(sevWords.toHtmlEscaped(),
                                 when.isEmpty() || when == QLatin1String("-") ? QString() : QStringLiteral(" at ") + when.toHtmlEscaped(),
                                 f.value("what").toString().toHtmlEscaped(),
                                 f.value("fix").toString().isEmpty()
                                     ? QString()
                                     : QStringLiteral("<br><span style='color:%1'>%2 %3</span>")
                                           .arg(QString::fromLatin1(muted), tr("Fix:").toHtmlEscaped(),
                                                f.value("fix").toString().toHtmlEscaped()));
            }
            html += QStringLiteral("</ul>");
        }
        const QJsonArray notDone = result.value("not_done").toArray();
        QStringList names;
        for (const auto &n : notDone)
            if (n.toString() != QLatin1String("editorial review")) // the verdict's own words say it
                names << n.toString();
        if (!names.isEmpty()) {
            html += QStringLiteral("<p style='color:%1'>%2</p>")
                        .arg(QString::fromLatin1(muted),
                             tr("Not checked here: %1. Your AI can give a second opinion on story, pacing and shots.")
                                 .arg(names.join(QStringLiteral(", ")))
                                 .toHtmlEscaped());
        }
        if (!m_credits.isEmpty()) {
            html += QStringLiteral("<p><b>%1</b></p><p>%2</p><p><a href='copy:credits'>%3</a></p>")
                        .arg(tr("This video owes a credit line").toHtmlEscaped(),
                             creditText(m_credits).toHtmlEscaped().replace(QLatin1Char('\n'), QStringLiteral("<br>")),
                             tr("Copy it for the video's description").toHtmlEscaped());
        }
        m_result->setHtml(html);
        m_result->show();
        m_report->setVisible(QFileInfo::exists(m_reportFile));
        m_askAi->show();
        m_run->say(tr("Checked %1.").arg(QFileInfo(m_video->text()).fileName()));
        m_go->setText(tr("Check it again"));
    }

    static const char *ok_colour() { return LetItEditColors::ok; }

    void askAi()
    {
        const QString video = m_video->text().trimmed();
        const QString project = m_window->fileName();
        const QString text
            = QObject::tr("Review my finished video %1%2 with letitedit_review_bundle (video=that file%3, critic='run'), "
                          "then tell me in plain words what to fix first, with times. Don't change anything yet. The "
                          "measured checks already ran: verdict %4, the full report is %5.")
                  .arg(nativePath(video),
                       project.isEmpty() ? QString() : QObject::tr(" (project %1)").arg(nativePath(project)),
                       project.isEmpty() ? QString() : QObject::tr(", project=that project"),
                       m_verdict,
                       nativePath(m_reportFile));
        if (ask(m_window, text, QObject::tr("Give me a second opinion on %1").arg(QFileInfo(video).fileName()),
                QObject::tr("Your AI is watching your video; its opinion appears in the chat.")))
            accept();
    }

    MainWindow *m_window;
    QLineEdit *m_video = nullptr;
    RunBox *m_run = nullptr;
    QTextBrowser *m_result = nullptr;
    QPushButton *m_stop = nullptr;
    QPushButton *m_report = nullptr;
    QPushButton *m_askAi = nullptr;
    QPushButton *m_go = nullptr;
    QString m_verdict;
    QString m_reportFile;
    QJsonArray m_credits;
};

QPointer<QDialog> g_check; // the open Check my video (not modal: the editor stays usable)

} // namespace

void showCheckVideo(MainWindow *window, const QString &video)
{
    if (g_check) {
        g_check->raise();
        g_check->activateWindow();
        return;
    }
    const QString file = !video.isEmpty() ? video : lastExport();
    auto dialog = new CheckVideoDialog(window, file);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    g_check = dialog;
    dialog->show();
}

void addCheckVideoState(QJsonObject &out)
{
    if (auto d = openDialog<CheckVideoDialog>(QStringLiteral("checkVideoDialog")))
        out.insert("check_video", d->qaState());
}

} // namespace LeFeatures
