/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The helpers the bridge's files share (claudebridge.cpp and letitedit/bridge/): the error a command
 * throws, reading a request's parameters, describing actions, dialogs and filters, checking a track and a clip.
 */
#ifndef BRIDGEHELPERS_H
#define BRIDGEHELPERS_H

#include "letitedit/bridge/claudebridge.h"
#include "letitedit/panels/musicpicker.h"
#include "letitedit/export/othersizes.h"
#include "letitedit/export/exportchecks.h"
#include "letitedit/airoot.h"
#include "letitedit/panels/aiaudiolibrary.h"
#include "letitedit/bridge/aicollaboration.h"
#include "letitedit/panels/hookpanel.h"
#include "letitedit/panels/myassets.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/review/reviewmode.h"
#include "letitedit/dialogs/lefeatures.h"
#include "jobqueue.h"
#include "jobs/abstractjob.h"
#include "letitedit/chat/aichatpanel.h"
#include "models/subtitlesselectionmodel.h"
#include "settings.h"
#include <QStandardPaths>
#include <QCryptographicHash>
#include <QLineEdit>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QFormLayout>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QComboBox>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QTabWidget>
#include <QDialogButtonBox>
#include <QMenuBar>
#include <QDateTime>
#include <QPixmap>
#include <QWindow>
#include <qpa/qwindowsysteminterface.h>

#include "Logger.h"
#include "actions.h"
#include "commands/timelinecommands.h"
#include "commands/subtitlecommands.h"
#include "controllers/filtercontroller.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "qmltypes/qmlutilities.h"
#include "videowidget.h"
#include "mltcontroller.h"
#include "player.h"
#include "models/markersmodel.h"
#include "models/attachedfiltersmodel.h"
#include "models/metadatamodel.h"
#include "models/multitrackmodel.h"
#include "models/subtitles.h"
#include "models/subtitlesmodel.h"
#include "qmltypes/qmlfilter.h"
#include "qmltypes/qmlmetadata.h"

#include <QAbstractButton>
#include <QApplication>
#include <QDialog>
#include <QLabel>
#include <QMessageBox>
#include <QDockWidget>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalServer>
#include <QLocalSocket>
#include <QTimer>
#include <QUndoStack>
#include <QDir>
#include <QLockFile>
#include <QSaveFile>
#include <QRegularExpression>

namespace BridgeHelpers {

class BridgeError
{
public:
    explicit BridgeError(const QString &message)
        : message(message)
    {}
    QString message;
};

QString requireString(const QJsonObject &params, const char *key);
int requireInt(const QJsonObject &params, const char *key);
QString jsonToPropertyString(const QJsonValue &value);
QJsonObject actionToJson(const QString &name, QAction *action);
QAction *findAction(const QString &name);
QString plainButtonText(const QAbstractButton *button);
QJsonObject describeDialog(QWidget *dialog);
QJsonObject metadataToJson(QmlMetadata *meta);
MultitrackModel *checkedTrack(int track);
void checkClip(MultitrackModel *model, int track, int clip);
int trackEnd(MultitrackModel *model, int track);

} // namespace BridgeHelpers

#endif // BRIDGEHELPERS_H
