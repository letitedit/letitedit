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

// The feature dialogs of letitedit (Import a style, Animated title, Sync sound, Check my video, Dub): what
// their files in letitedit/dialogs/ share with lefeatures.cpp. The rest of the editor sees lefeatures.h.
#ifndef FEATUREHELPERS_H
#define FEATUREHELPERS_H

#include "letitedit/dialogs/lefeatures.h"

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

// the video and sound file patterns (defined in lefeatures.cpp)
extern const QStringList kVideoFiles;
extern const QStringList kSoundFiles;

QLabel *headingLabel(const QString &text, QWidget *parent);
QLabel *mutedLabel(const QString &text, QWidget *parent);
QString nativePath(const QString &path);
void showChat(MainWindow *window);
// One request to the person's AI: the chat shows `summary`, the AI gets `text`. False when it couldn't take it.
bool ask(MainWindow *window, const QString &text, const QString &summary, const QString &busyLine);
// The paths in a "folder or files" field: one folder, or files separated by ';'.
QStringList pathsIn(const QString &text);
// What a folder or a list of files holds, in words ("3 videos and 1 sound file"); counts are returned too.
QString countFiles(const QStringList &paths, int *videos = nullptr, int *sounds = nullptr);

// A progress bar and a status line under a dialog's fields, and the run behind them (an app_tools command).
class RunBox : public QWidget
{
public:
    RunBox(QWidget *parent, const QString &prefix)
        : QWidget(parent)
        , run(new LeToolRun(this))
    {
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(0, 0, 0, 0);
        column->setSpacing(4);
        bar = new QProgressBar(this);
        bar->setObjectName(prefix + QStringLiteral("Progress"));
        bar->setRange(0, 1000);
        bar->setTextVisible(false);
        bar->setFixedHeight(8);
        bar->hide();
        column->addWidget(bar);
        status = new QLabel(this);
        status->setObjectName(prefix + QStringLiteral("Status"));
        status->setWordWrap(true);
        status->setTextInteractionFlags(Qt::TextSelectableByMouse);
        column->addWidget(status);
        run->progress = [this](double f, const QString &words) {
            bar->setRange(0, 1000);
            bar->setValue(qRound(qBound(0.0, f, 1.0) * 1000));
            if (!words.isEmpty())
                say(m_prefixWords.isEmpty() ? words : m_prefixWords + QStringLiteral(": ") + words);
        };
        run->waiting = [this](const QString &words) {
            if (!words.isEmpty()) {
                bar->setRange(0, 0); // busy, no fraction while it waits
                say(words);
            } else {
                bar->setRange(0, 1000);
                say(m_firstWords);
            }
        };
        run->done = [this](bool ok, const QJsonObject &result, const QString &why) {
            bar->hide();
            if (done)
                done(ok, result, why);
        };
    }

    void start(const QString &command, const QStringList &args, bool heavy, const QString &lockName,
               const QString &firstWords, const QString &prefixWords = QString())
    {
        m_firstWords = firstWords;
        m_prefixWords = prefixWords;
        bar->setRange(0, 1000);
        bar->setValue(0);
        bar->show();
        say(firstWords);
        run->start(command, args, heavy, lockName);
    }

    void say(const QString &text, bool problem = false)
    {
        status->setStyleSheet(problem ? QStringLiteral("color: #ff8a80;") : QString());
        status->setText(text);
    }

    bool running() const { return run->running(); }

    LeToolRun *run;
    QProgressBar *bar = nullptr;
    QLabel *status = nullptr;
    std::function<void(bool, const QJsonObject &, const QString &)> done;

private:
    QString m_firstWords;
    QString m_prefixWords;
};

template<typename T>
T *openDialog(const QString &name)
{
    for (auto *top : QApplication::topLevelWidgets())
        if (top->isVisible() && top->objectName() == name)
            return dynamic_cast<T *>(top);
    return nullptr;
}

// Each dialog file's part of LeFeatures::state(): the dialog's state when it is open
void addAnimatedTitleState(QJsonObject &out); // animatedtitledialog.cpp
void addSyncSoundState(QJsonObject &out); // syncsounddialog.cpp
void addCheckVideoState(QJsonObject &out); // checkvideodialog.cpp

} // namespace LeFeatures

#endif // FEATUREHELPERS_H
