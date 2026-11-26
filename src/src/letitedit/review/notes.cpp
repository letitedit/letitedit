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

// Review: the notes (adding, choosing, deleting, recording one again) and the list of them.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"

namespace ReviewMode {

// "Record it again" for the spoken note selected (or the last one made).
int ReviewWindow::againNote() const
{
    const int row = m_list->currentRow();
    if (row >= 0 && m_list->item(row)) {
        const int i = m_list->item(row)->data(Qt::UserRole).toInt();
        if (i >= 0 && i < m_notes.size() && m_notes[i].take)
            return i;
        return -1;
    }
    for (int i = m_notes.size() - 1; i >= 0; --i)
        if (m_notes[i].take && m_notes[i].id == m_lastTakeId)
            return i;
    return -1;
}

void ReviewWindow::updateAgain()
{
    if (m_again)
        m_again->setVisible(!m_recording && !m_transcribing && againNote() >= 0);
}

void ReviewWindow::recordAgain()
{
    const int i = againNote();
    if (i < 0 || m_recording || m_transcribing)
        return;
    const int frame = m_notes[i].frame;
    for (const QString &file : files(m_notes[i]))
        QFile::remove(QDir(m_dir).filePath(file));
    m_notes.removeAt(i);
    changed();
    m_window->seekTimeline(qMax(0, frame));
    m_position = qMax(0, frame);
    startTake();
    m_status->setText(tr("Recording again from %1. Talk and draw, then press T.").arg(stamp(frame / m_fps)));
}

int ReviewWindow::noteAt(int frame) const
{
    for (int i = 0; i < m_notes.size(); ++i)
        if (!m_notes[i].take && m_notes[i].frame == frame)
            return i;
    return -1;
}

// A drawing left without words becomes a note of its own when the video moves on.
void ReviewWindow::commitDraft()
{
    if (m_draft.isEmpty() || m_draftFrame < 0)
        return;
    Note n;
    n.id = m_nextId++;
    n.frame = m_draftFrame;
    n.strokes = m_draft;
    n.image = m_draftImage;
    n.shot = m_draftShot;
    m_notes.append(n);
    if (m_lastMarkId == 0) m_lastMarkId = n.id;
    m_draft.clear();
    m_draftFrame = -1;
    m_draftImage = QImage();
    m_draftShot = SharedFrame();
    sortNotes();
    changed();
}

void ReviewWindow::addNote()
{
    const QString text = m_input->text().trimmed();
    if (text.isEmpty()) {
        m_status->setText(tr("Type what should change first, or turn on Talk while I draw."));
        return;
    }
    if (m_whole->isChecked()) {
        Note n;
        n.id = m_nextId++;
        n.text = text;
        m_notes.append(n);
        m_whole->setChecked(false);
    } else {
        int i = noteAt(m_position);
        if (i < 0) {
            Note n;
            n.id = m_nextId++;
            n.frame = m_position;
            n.strokes = m_draft;
            const bool draftHere = m_draftFrame == m_position;
            if (Timing::get().legacy)
                n.image = m_draftImage.isNull() || !draftHere ? m_canvas->image : m_draftImage;
            else {
                n.image = draftHere ? m_draftImage : captureScenePicture();
                if (n.image.isNull())
                    n.shot = draftHere && m_draftShot.is_valid() ? m_draftShot : m_frame;
            }
            m_notes.append(n);
            m_draft.clear();
            m_draftFrame = -1;
            m_draftImage = QImage();
            m_draftShot = SharedFrame();
            i = m_notes.size() - 1;
        }
        Note &n = m_notes[i];
        n.text = n.text.isEmpty() ? text : n.text + QStringLiteral(" ") + text;
    }
    m_input->clear();
    m_status->clear();
    sortNotes();
    changed();
}

void ReviewWindow::undoMark()
{
    if (auto strokes = activeStrokes(); strokes && !strokes->isEmpty()) {
        strokes->removeLast();
        if (m_recording) {
            m_canvas->update();
            return;
        }
        dropIfEmpty();
        changed();
    }
}

void ReviewWindow::dropIfEmpty()
{
    const int i = noteAt(m_position);
    if (i >= 0 && m_notes[i].strokes.isEmpty() && m_notes[i].text.isEmpty() && m_notes[i].audio.isEmpty())
        m_notes.removeAt(i);
}

void ReviewWindow::deleteSelected()
{
    auto item = m_list->currentItem();
    if (!item || m_recording)
        return;
    const int i = item->data(Qt::UserRole).toInt();
    if (i < 0 || i >= m_notes.size())
        return;
    for (const QString &file : files(m_notes[i]))
        QFile::remove(QDir(m_dir).filePath(file));
    m_notes.removeAt(i);
    changed();
}

void ReviewWindow::sortNotes()
{
    std::stable_sort(m_notes.begin(), m_notes.end(), [](const Note &a, const Note &b) {
        return (a.frame < 0) != (b.frame < 0) ? a.frame < 0 : a.frame < b.frame;
    });
}

void ReviewWindow::changed()
{
    save();
    refresh();
    updateReviewMarkup();
}

void ReviewWindow::refreshActive()
{
    const int active = noteAt(m_position);
    m_scrubber->activePin = active >= 0 ? m_notes[active].frame : -1;
    if (active >= 0)
        for (int row = 0; row < m_list->count(); ++row)
            if (m_list->item(row)->data(Qt::UserRole).toInt() == active)
                m_list->setCurrentRow(row);
    m_scrubber->update();
}

void ReviewWindow::refresh()
{
    m_list->clear();
    m_scrubber->pins.clear();
    for (int i = 0; i < m_notes.size(); ++i) {
        const Note &n = m_notes[i];
        QStringList extras;
        if (n.take && !n.strokes.isEmpty())
            extras << (n.strokes.size() == 1 ? tr("1 mark") : tr("%1 marks").arg(n.strokes.size()));
        else if (!n.strokes.isEmpty())
            extras << tr("drawing");
        if (!n.audio.isEmpty())
            extras << tr("spoken");
        QString when = n.frame < 0 ? tr("Whole video") : stamp(n.frame / m_fps);
        if (n.take && n.endFrame > n.frame)
            when += QStringLiteral("-") + stamp(n.endFrame / m_fps);
        QString text = n.text.isEmpty() ? tr("(see the drawing)") : n.text;
        if (!extras.isEmpty())
            text += QStringLiteral("  [%1]").arg(extras.join(QStringLiteral(", ")));
        auto item = new QListWidgetItem(QStringLiteral("%1   %2").arg(when, text));
        item->setData(Qt::UserRole, i);
        item->setToolTip(n.take ? script(n) : n.text);
        m_list->addItem(item);
        if (n.frame >= 0)
            m_scrubber->pins << n.frame;
    }
    // Send closes a note still being spoken and sends it with the rest once its words are in (T210)
    const bool stuck = !m_live && m_notes.isEmpty() && NoteQueue::of(m_window).stuck(); // T221: Send tries them again
    m_submit->setEnabled((!m_notes.isEmpty() || (m_recording && !m_live) || stuck) && !m_sending && !m_sendWhenWritten
                         && !(m_live && m_transcribing));
    for (auto it = m_unwritten.begin(); it != m_unwritten.end();) // notes deleted since
        it = noteIndex(*it) < 0 ? m_unwritten.erase(it) : std::next(it);
    m_retry->setVisible(!m_unwritten.isEmpty() && !m_recording && !m_transcribing);
    m_submit->setText(stuck                 ? tr("Send the waiting notes again")
                      : m_notes.isEmpty()   ? tr("Send to your AI")
                      : m_notes.size() == 1 ? tr("Send 1 note to your AI")
                                            : tr("Send %1 notes to your AI").arg(m_notes.size()));
    refreshActive();
    updateAgain();
    m_canvas->update();
    if (m_live)
        refreshLiveList();
}

} // namespace ReviewMode
