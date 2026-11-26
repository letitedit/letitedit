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

// Sync sound: line up a second recording with the video by its sound.
// (Split out of lefeatures.cpp; what it shares with it is in featurehelpers.h.)

#include "featurehelpers.h"

namespace LeFeatures {

namespace {

class SyncSoundDialog : public QDialog
{
public:
    explicit SyncSoundDialog(MainWindow *window)
        : QDialog(window)
        , m_window(window)
    {
        setObjectName(QStringLiteral("syncSoundDialog"));
        setWindowTitle(tr("Line up separate sound"));
        setMinimumWidth(680);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        column->addWidget(headingLabel(tr("Line up a separate mic or a second camera"), this));
        column->addWidget(mutedLabel(tr("Recorded the sound on a separate mic, a recorder or a second camera? letitedit "
                                        "lines everything up by its sound (a clap helps, but isn't needed) and makes a "
                                        "new project with the good sound under every camera clip. Your files aren't "
                                        "changed."),
                                     this));
        auto row = new QHBoxLayout;
        m_source = new QLineEdit(this);
        m_source->setObjectName(QStringLiteral("syncSoundSource"));
        m_source->setAccessibleName(tr("The footage and the sound recordings"));
        m_source->setPlaceholderText(tr("The folder with the camera clips and the sound recordings, or the files"));
        connect(m_source, &QLineEdit::textChanged, this, [this]() { count(); });
        auto folder = new QPushButton(tr("Choose folder..."), this);
        folder->setObjectName(QStringLiteral("syncSoundFolder"));
        connect(folder, &QPushButton::clicked, this, [this]() {
            const QString chosen = QFileDialog::getExistingDirectory(this, tr("Folder with the footage and recordings"),
                                                                     pathsIn(m_source->text()).value(0, Settings.openPath()),
                                                                     Util::getFileDialogOptions());
            if (!chosen.isEmpty())
                m_source->setText(nativePath(chosen));
        });
        auto files = new QPushButton(tr("Choose files..."), this);
        files->setObjectName(QStringLiteral("syncSoundFiles"));
        connect(files, &QPushButton::clicked, this, [this]() {
            const QStringList chosen = QFileDialog::getOpenFileNames(
                this, tr("Camera clips and sound recordings"), Settings.openPath(),
                tr("Videos and sounds (%1)").arg((kVideoFiles + kSoundFiles).join(QLatin1Char(' '))), nullptr,
                Util::getFileDialogOptions());
            QStringList shown;
            for (const auto &c : chosen)
                shown << nativePath(c);
            if (!shown.isEmpty())
                m_source->setText(shown.join(QStringLiteral("; ")));
        });
        row->addWidget(m_source, 1);
        row->addWidget(folder);
        row->addWidget(files);
        column->addLayout(row);
        m_found = mutedLabel(QString(), this);
        m_found->setObjectName(QStringLiteral("syncSoundFound"));
        column->addWidget(m_found);
        auto saveRow = new QHBoxLayout;
        saveRow->addWidget(new QLabel(tr("Save the new project as"), this));
        m_project = new QLineEdit(this);
        m_project->setObjectName(QStringLiteral("syncSoundProject"));
        saveRow->addWidget(m_project, 1);
        auto change = new QPushButton(tr("Change..."), this);
        connect(change, &QPushButton::clicked, this, [this]() {
            const QString chosen = QFileDialog::getSaveFileName(this, tr("Save the lined-up project as"), m_project->text(),
                                                                tr("letitedit project (*.mlt)"), nullptr,
                                                                Util::getFileDialogOptions());
            if (!chosen.isEmpty())
                m_project->setText(nativePath(chosen.endsWith(QLatin1String(".mlt"), Qt::CaseInsensitive)
                                                  ? chosen
                                                  : chosen + QStringLiteral(".mlt")));
        });
        saveRow->addWidget(change);
        column->addLayout(saveRow);
        m_run = new RunBox(this, QStringLiteral("syncSound"));
        column->addWidget(m_run);
        m_picture = new QLabel(this);
        m_picture->setObjectName(QStringLiteral("syncSoundPicture"));
        m_picture->setAlignment(Qt::AlignCenter);
        m_picture->hide();
        column->addWidget(m_picture);
        auto buttons = new QHBoxLayout;
        auto close = new QPushButton(tr("Close"), this);
        close->setObjectName(QStringLiteral("syncSoundClose"));
        connect(close, &QPushButton::clicked, this, &QDialog::reject);
        m_stop = new QPushButton(tr("Stop"), this);
        m_stop->setObjectName(QStringLiteral("syncSoundStop"));
        m_stop->hide();
        connect(m_stop, &QPushButton::clicked, this, [this]() { m_run->run->cancel(); });
        m_show = new QPushButton(tr("Show in folder"), this);
        m_show->setObjectName(QStringLiteral("syncSoundShow"));
        m_show->hide();
        connect(m_show, &QPushButton::clicked, this, [this]() { Util::showInFolder(m_made); });
        m_open = new QPushButton(tr("Open the lined-up project"), this);
        m_open->setObjectName(QStringLiteral("syncSoundOpen"));
        m_open->setProperty("studioPrimary", true);
        m_open->hide();
        connect(m_open, &QPushButton::clicked, this, [this]() {
            const QString made = m_made;
            accept();
            QTimer::singleShot(0, m_window, [w = m_window, made]() { w->open(made); });
        });
        m_go = new QPushButton(tr("Line them up"), this);
        m_go->setObjectName(QStringLiteral("syncSoundGo"));
        m_go->setProperty("studioPrimary", true);
        m_go->setDefault(true);
        connect(m_go, &QPushButton::clicked, this, [this]() { go(); });
        buttons->addWidget(close);
        buttons->addStretch(1);
        buttons->addWidget(m_stop);
        buttons->addWidget(m_show);
        buttons->addWidget(m_open);
        buttons->addWidget(m_go);
        column->addLayout(buttons);
        m_run->done = [this](bool ok, const QJsonObject &result, const QString &why) { finished(ok, result, why); };
        m_source->setText(nativePath(Settings.openPath()));
        count();
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
                           {"found", m_found->text()}, {"project", m_project->text()}, {"made", m_made},
                           {"picture", !m_picture->pixmap().isNull()}};
    }

private:
    void count()
    {
        const QStringList paths = pathsIn(m_source->text());
        int videos = 0, sounds = 0;
        const QString words = countFiles(paths, &videos, &sounds);
        m_found->setText(paths.isEmpty() ? QString()
                         : words.isEmpty() ? tr("No videos or sound files there.")
                         : videos + sounds < 2 ? tr("Found %1. Lining up needs at least two recordings of the same "
                                                    "moment.").arg(words)
                                               : tr("Found %1.").arg(words));
        // the new project goes in Videos\letitedit, never into the footage folder
        const QFileInfo first(paths.value(0));
        QString name = first.isDir() ? first.fileName() : first.dir().dirName();
        if (name.isEmpty())
            name = tr("footage");
        const QString videosDir = QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
        m_project->setText(nativePath(QStringLiteral("%1/letitedit/%2 lined up/%2 lined up.mlt").arg(videosDir, name)));
    }

    void go()
    {
        const QStringList paths = pathsIn(m_source->text());
        int videos = 0, sounds = 0;
        countFiles(paths, &videos, &sounds);
        if (videos + sounds < 2) {
            m_run->say(tr("Choose the folder (or the files) with at least two recordings of the same moment: the "
                          "camera clips and the separate sound."),
                       true);
            return;
        }
        if (m_project->text().trimmed().isEmpty()) {
            m_run->say(tr("Choose where to save the new project."), true);
            return;
        }
        QStringList args;
        for (const auto &p : paths)
            args << p;
        args << QStringLiteral("--project") << m_project->text().trimmed();
        m_go->setEnabled(false);
        m_source->setEnabled(false);
        m_stop->show();
        m_picture->hide();
        m_run->start(QStringLiteral("sync"), args, true, QStringLiteral("letitedit line up sound"),
                     tr("Listening to every recording..."));
    }

    void finished(bool ok, const QJsonObject &result, const QString &why)
    {
        m_go->setEnabled(true);
        m_source->setEnabled(true);
        m_stop->hide();
        if (!ok) {
            m_run->say(why.isEmpty() ? tr("Stopped. Nothing was made.") : tr("They couldn't be lined up: %1").arg(why),
                       !why.isEmpty());
            return;
        }
        const QJsonArray placed = result.value("placed").toArray();
        const QJsonArray missed = result.value("not_placed").toArray();
        QStringList lines;
        lines << tr("Lined up %1 of %2 recordings.").arg(placed.size()).arg(placed.size() + missed.size());
        for (const auto &m : missed) {
            const QJsonObject o = m.toObject();
            lines << tr("Not lined up: %1 (%2).").arg(o.value("file").toString(), o.value("why").toString());
        }
        int unsure = 0;
        for (const auto &p : placed)
            if (p.toObject().value("level").toString() == QLatin1String("likely")
                || p.toObject().value("level").toString() == QLatin1String("assumed"))
                ++unsure;
        if (unsure)
            lines << tr("%1 of them are a likely match rather than a sure one: watch those joins.").arg(unsure);
        m_made = result.value("project").toString();
        if (!m_made.isEmpty())
            lines << tr("The new project: %1").arg(nativePath(m_made));
        m_run->say(lines.join(QLatin1Char('\n')));
        const QPixmap sheet(result.value("sheet").toString());
        if (!sheet.isNull()) {
            m_picture->setPixmap(sheet.scaledToWidth(qMin(640, sheet.width()), Qt::SmoothTransformation));
            m_picture->show();
        }
        m_open->setVisible(!m_made.isEmpty());
        m_show->setVisible(!m_made.isEmpty());
        m_go->setText(tr("Line them up again"));
        m_go->setProperty("studioPrimary", false);
        m_go->style()->unpolish(m_go);
        m_go->style()->polish(m_go);
    }

    MainWindow *m_window;
    QLineEdit *m_source = nullptr;
    QLabel *m_found = nullptr;
    QLineEdit *m_project = nullptr;
    RunBox *m_run = nullptr;
    QLabel *m_picture = nullptr;
    QPushButton *m_stop = nullptr;
    QPushButton *m_show = nullptr;
    QPushButton *m_open = nullptr;
    QPushButton *m_go = nullptr;
    QString m_made;
};

} // namespace

void showSyncSound(MainWindow *window)
{
    SyncSoundDialog dialog(window);
    dialog.exec();
}

void addSyncSoundState(QJsonObject &out)
{
    if (auto d = openDialog<SyncSoundDialog>(QStringLiteral("syncSoundDialog")))
        out.insert("sync_sound", d->qaState());
}

} // namespace LeFeatures
