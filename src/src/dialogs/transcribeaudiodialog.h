/*
 * Copyright (c) 2024-2026 Meltytech, LLC
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

#ifndef TRANSCRIBEAUDIODIALOG_H
#define TRANSCRIBEAUDIODIALOG_H

#include "models/extensionmodel.h"

#include <QDialog>

class QAbstractButton;
class QCheckBox;
class QGridLayout;
class QLabel;
class QPushButton;
class QComboBox;
class QDialogButtonBox;
class QLineEdit;
class QListWidget;
class QSpinBox;
class QTreeView;

class TranscribeAudioDialog : public QDialog
{
    Q_OBJECT

public:
    explicit TranscribeAudioDialog(const QString &trackName, QWidget *parent);
    QString name();
    QString language();
    QList<int> tracks();
    bool translate();
    int maxLineLength();
    bool includeNonspoken();
    bool useGpu();
    bool beginner() const { return m_beginner; }

protected:
    virtual void showEvent(QShowEvent *event) override;

private slots:
    void onButtonClicked(QAbstractButton *button);
    void onModelRowClicked(const QModelIndex &index);

private:
    // letitedit's workspace: "Make captions" for beginners - the speech in the video by default, whether it is ready
    // and how long it takes, any download explained before it is offered, the tracks, GPU and model under Advanced
    void makeBeginnerFlow(QGridLayout *grid);
    void updateReadiness();
    bool m_beginner = false;
    QLabel *m_readiness = nullptr;
    QPushButton *m_download = nullptr;
    QWidget *m_advanced = nullptr;
    void downloadModel(int index);
    void setCurrentModel(int index);
    void updateWhisperStatus();
    void showModelContextMenu(QPoint p);
    ExtensionModel m_model;
    QLineEdit *m_name;
    QComboBox *m_lang;
    QCheckBox *m_translate;
    QSpinBox *m_maxLength;
    QCheckBox *m_nonspoken;
    QCheckBox *m_useGpu;
    QListWidget *m_trackList;
    QWidget *m_configWidget;
    QLineEdit *m_exeLabel;
    QLineEdit *m_modelLabel;
    QDialogButtonBox *m_buttonBox;
    QTreeView *m_table;
};

#endif // TRANSCRIBEAUDIODIALOG_H
