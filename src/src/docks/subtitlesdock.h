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

#ifndef SUBTITLESDOCK_H
#define SUBTITLESDOCK_H

#include <MltPlaylist.h>
#include <QDockWidget>
#include <QMap>

class SubtitlesModel;
class SubtitlesSelectionModel;
class QComboBox;
class QItemSelection;
class QLabel;
class QLineEdit;
class QTextEdit;
class QTreeView;
class QVBoxLayout;
class SpeechDialog;

class SubtitlesDock : public QDockWidget
{
    Q_OBJECT

public:
    explicit SubtitlesDock(QWidget *parent = 0);
    ~SubtitlesDock();
    void setModel(SubtitlesModel *model, SubtitlesSelectionModel *selectionModel);
    void installStudioPresentation();
    void importSrtFromFile(const QString &srtPath,
                           const QString &trackName,
                           const QString &lang,
                           bool includeNonspoken);

    // letitedit: caption editing from the timeline lanes and the video player.
    Q_INVOKABLE void selectTrack(int trackIndex);
    Q_INVOKABLE void editTrackAt(int trackIndex);
    Q_INVOKABLE bool editCaption(int trackIndex, int itemIndex);
    Q_INVOKABLE QVariantList captionsAtPlayhead();
    Q_INVOKABLE bool selectCaption(int trackIndex, int itemIndex);
    Q_INVOKABLE bool removeSelectedCaptions();
    Q_INVOKABLE bool hasSelectedCaptions();

    // letitedit "My style": the shown caption track's look as filter properties (empty if not shown on the video),
    // and a look applied to it as one undo step (false if the captions are not on the video).
    QMap<QString, QString> shownCaptionProperties() const;
    bool applyCaptionProperties(const QMap<QString, QString> &properties);
    // The caption look new burn-ins use: a saved style's properties, or one of the four looks.
    static QMap<QString, QString> chosenCaptionProperties();

signals:
    void seekRequested(int pos);
    void addAllTimeline(Mlt::Playlist *, bool skipProxy, bool emptyTrack);
    void createOrEditFilterOnOutput(Mlt::Filter *, const QStringList &key_properties);

private slots:
    void onPositionChanged(int position);
    void onStartColumnToggled(bool checked);
    void onEndColumnToggled(bool checked);
    void onDurationColumnToggled(bool checked);

protected:
    void resizeEvent(QResizeEvent *) Q_DECL_OVERRIDE;
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void buildStudioCaptionChoices(QWidget *body, QVBoxLayout *column);
    void setupActions();
    void onCreateOrEditRequested();
    void onAddRequested();
    void onRemoveRequested();
    void onSetStartRequested();
    void onSetEndRequested();
    void onMoveRequested();
    void onTextEdited();
    void onModelReset();
    void updateActionAvailablity();
    void addSubtitleTrack();
    void removeSubtitleTrack();
    void editSubtitleTrack();
    void refreshTracksCombo();
    void importSubtitles();
    void exportSubtitles();
    void onItemDoubleClicked(const QModelIndex &index);
    void resizeTextWidgets();
    void updateTextWidgets();
    void setCurrentItem(int trackIndex, int itemIndex);
    void refreshWidgets();
    void selectItemForTime();
    QString availableTrackName();
    bool trackNameExists(const QString &name);
    void ensureTrackExists();
    void burnInOnTimeline();
    void burnInOnTimelineWithProperties(const QMap<QString, QString> &properties);
    void applyCaptionLook(const QString &key);
    void editWordList();
    void translateCaptions();
    int applyWordList(int trackIndex);
    static QList<QPair<QString, QString>> wordList();
    void generateTextOnTimeline();
    void speechToText();
    void speechToTextWithBridge(const QString &trackName, const QString &language);
    void textToSpeech();
    bool findWhisperExe();
    void seekToText(QString text, int step);

    SubtitlesModel *m_model;
    SubtitlesSelectionModel *m_selectionModel;
    QLabel *m_addToTimelineLabel;
    QComboBox *m_trackCombo;
    QTreeView *m_treeView;
    QTextEdit *m_text;
    QTextEdit *m_prev;
    QTextEdit *m_next;
    QLabel *m_prevLabel;
    QLabel *m_textLabel;
    QLabel *m_nextLabel;
    QLineEdit *m_searchField;
    int m_pos;
    bool m_textEditInProgress;
    bool m_showAfterImport = false; // speech-to-text captions go straight into the video
    std::unique_ptr<SpeechDialog> m_speechDialog;
};

#endif // SUBTITLESDOCK_H
