/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef STUDIOTEXTPANEL_H
#define STUDIOTEXTPANEL_H
#include "actions.h"
#include "commands/timelinecommands.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "shotcut_mlt_properties.h"
#include <MltFilter.h>
#include <MltPlaylist.h>
#include <QtWidgets>

class StudioTextPanel : public QWidget
{
public:
    explicit StudioTextPanel(MainWindow *window, QWidget *parent) : QWidget(parent), m_window(window)
    {
        setObjectName(QStringLiteral("studioTextPanel"));
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(16, 14, 16, 16);
        column->setSpacing(12);
        auto intro = new QLabel(tr("Add words to your video"), this);
        m_intro = intro;
        intro->setProperty("studioHeading", true);
        column->addWidget(intro);
        auto hint = new QLabel(tr("Type below, choose a look, then add it at the playhead."), this);
        m_hint = hint;
        hint->setWordWrap(true);
        hint->setProperty("studioMuted", true);
        column->addWidget(hint);
        // Two different things, kept apart: captions of what is said (made from speech) and text you type.
        auto captionsTitle = new QLabel(tr("Captions of what's said"), this);
        captionsTitle->setStyleSheet(QStringLiteral("font-weight: 600;"));
        column->addWidget(captionsTitle);
        auto captionsRow = new QHBoxLayout;
        captionsRow->setSpacing(6);
        auto speech = new QPushButton(tr("Make captions"), this);
        speech->setObjectName(QStringLiteral("studioGenerateCaptions"));
        speech->setToolTip(tr("Listen to the video and write captions of everything that's said"));
        speech->setMinimumHeight(40);
        connect(speech, &QPushButton::clicked, this, [this]() {
            if (auto a = m_window->findChild<QAction *>(QStringLiteral("studioCaptionsAction")))
                a->trigger();
            Actions["subtitleSpeechToTextAction"]->trigger();
        });
        auto captions = new QPushButton(tr("Edit captions"), this);
        captions->setObjectName(QStringLiteral("studioEditCaptions"));
        captions->setToolTip(tr("Fix words, timing and the look of the captions"));
        captions->setMinimumHeight(40);
        connect(captions, &QPushButton::clicked, this, [this]() {
            if (auto a = m_window->findChild<QAction *>(QStringLiteral("studioCaptionsAction")))
                a->trigger();
        });
        captionsRow->addWidget(speech, 1);
        captionsRow->addWidget(captions, 1);
        column->addLayout(captionsRow);
        // letitedit: a moving title, name tag, place name, chapter card or end card (motion clips)
        auto animated = new QPushButton(tr("Animated title…"), this);
        animated->setObjectName(QStringLiteral("studioAnimatedTitle"));
        animated->setToolTip(tr("A moving title, name tag, place name, chapter card, count-up or end card, in this "
                                "video's style"));
        animated->setMinimumHeight(40);
        connect(animated, &QPushButton::clicked, this, []() {
            if (auto a = Actions["animatedTitleAction"])
                a->trigger();
        });
        column->addWidget(animated);
        auto textTitle = new QLabel(tr("Add text"), this);
        textTitle->setStyleSheet(QStringLiteral("font-weight: 600; margin-top: 8px;"));
        column->addWidget(textTitle);
        m_text = new QPlainTextEdit(this);
        m_text->setObjectName(QStringLiteral("studioTextContent"));
        m_text->setPlaceholderText(tr("Type your text…"));
        m_text->setAccessibleName(tr("Text to put in the video"));
        m_text->setMinimumHeight(76);
        m_text->setMaximumHeight(96);
        column->addWidget(m_text);
        auto choices = new QHBoxLayout;
        choices->setSpacing(6);
        m_styles = new QButtonGroup(this);
        const QStringList styles{tr("Title"), tr("Lower third"), tr("Small text")};
        for (int i = 0; i < styles.size(); ++i) {
            auto b = new QPushButton(styles[i], this);
            b->setCheckable(true);
            b->setMinimumHeight(40);
            b->setProperty("studioChoice", true);
            m_styles->addButton(b, i);
            choices->addWidget(b, 1);
        }
        m_styles->button(0)->setChecked(true);
        column->addLayout(choices);
        auto form = new QFormLayout;
        form->setRowWrapPolicy(QFormLayout::WrapLongRows);
        form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
        form->setSpacing(10);
        m_position = new QComboBox(this);
        m_position->setObjectName(QStringLiteral("studioTextPosition"));
        m_position->addItems({tr("Center"), tr("Bottom"), tr("Top")});
        form->addRow(tr("Position"), m_position);
        m_duration = new QDoubleSpinBox(this);
        m_duration->setObjectName(QStringLiteral("studioTextDuration"));
        m_duration->setRange(0.5, 60);
        m_duration->setDecimals(1);
        m_duration->setSingleStep(.5);
        m_duration->setValue(4);
        m_duration->setSuffix(tr(" seconds"));
        form->addRow(tr("On screen for"), m_duration);
        column->addLayout(form);
        m_preview = new QLabel(tr("Your text"), this);
        m_preview->setObjectName(QStringLiteral("studioTextPreview"));
        m_preview->setTextFormat(Qt::PlainText);
        m_preview->setWordWrap(true);
        m_preview->setMinimumHeight(90);
        m_preview->setMaximumHeight(120);
        column->addWidget(m_preview);
        m_context = new QLabel(this);
        m_context->setWordWrap(true);
        m_context->setProperty("studioMuted", true);
        column->addWidget(m_context);
        column->removeWidget(m_context);
        column->insertWidget(2, m_context);
        m_add = makeAction(QStringLiteral("studioAddTextAction"), tr("Add text to video"), [this]() { addText(); });
        m_apply = makeAction(QStringLiteral("studioApplyTextAction"), tr("Apply changes"), [this]() { applyText(); });
        m_primary = new QPushButton(tr("Add text to video"), this);
        m_primary->setObjectName(QStringLiteral("studioTextPrimary"));
        m_primary->setProperty("studioPrimary", true);
        connect(m_primary, &QPushButton::clicked, this, [this]() { (m_editTrack >= 0 ? m_apply : m_add)->trigger(); });
        column->addWidget(m_primary);
        auto fresh = new QPushButton(tr("+ New text"), this);
        m_new = fresh;
        fresh->setObjectName(QStringLiteral("studioNewText"));
        auto newAction = makeAction(QStringLiteral("studioNewTextAction"), tr("New text"), [this]() {
            m_editTrack = m_editClip = -1;
            m_window->timelineDock()->setSelection();
            m_text->clear();
            updateState();
            m_text->setFocus();
        });
        connect(fresh, &QPushButton::clicked, newAction, &QAction::trigger);
        column->addWidget(fresh);

        column->addStretch();
        connect(m_text, &QPlainTextEdit::textChanged, this, [this]() { updateState(); });
        connect(m_position, &QComboBox::currentIndexChanged, this, [this]() { updatePreview(); });
        connect(m_position, &QComboBox::activated, this, [this]() { m_positionDirty = true; });
        connect(m_styles, &QButtonGroup::idClicked, this, [this](int id) {
            m_styleDirty = m_positionDirty = true;
            m_position->setCurrentIndex(id == 0 ? 0 : 1);
            updatePreview();
        });
        connect(m_window->timelineDock(), &TimelineDock::selectionChanged, this, [this]() { readSelection(); });
        connect(m_window->undoStack(), &QUndoStack::indexChanged, this, [this]() {
            QTimer::singleShot(0, this, [this]() { readSelection(); });
        });
        updateState();
        if (auto scroll = qobject_cast<QScrollArea *>(parent)) {
            m_viewport = scroll->viewport();
            m_viewport->installEventFilter(this);
        }
    }

    void readSelection()
    {
        if (m_busy || !isVisible())
            return;
        auto tl = m_window->timelineDock();
        const auto selection = tl->selection();
        if (selection.size() == 1) {
            auto info = tl->model()->getClipInfo(selection[0].y(), selection[0].x());
            if (info && isTextProducer(info->producer)) {
                for (int i = 0; i < info->producer->filter_count(); ++i) {
                    std::unique_ptr<Mlt::Filter> filter(info->producer->filter(i));
                    if (filter && QString::fromUtf8(filter->get(kShotcutFilterProperty)) == QStringLiteral("dynamicText")) {
                        m_editTrack = selection[0].y();
                        m_editClip = selection[0].x();
                        m_text->setPlainText(QString::fromUtf8(filter->get("argument")).replace(QStringLiteral("\\#"), QStringLiteral("#")));
                        m_styles->button(qBound(0, filter->get_int("shotcut:studioStyle"), 2))->setChecked(true);
                        m_position->setCurrentIndex(qBound(0, filter->get_int("shotcut:studioPosition"), 2));
                        m_duration->setValue(info->frame_count / MLT.profile().fps());
                        m_styleDirty = m_positionDirty = false;
                        updateState();
                        return;
                    }
                }
            }
        }
        m_editTrack = m_editClip = -1;
        updateState();
    }

    QPushButton *primaryButton() const { return m_primary; }
    QPushButton *newButton() const { return m_new; }

protected:
    bool eventFilter(QObject *watched, QEvent *event) override
    {
        if (watched == m_viewport && event->type() == QEvent::Resize) {
            const bool compact = m_viewport->height() < 360;
            m_intro->setVisible(!compact);
            m_hint->setVisible(!compact);
            m_text->setMaximumHeight(compact ? 76 : 96);
        }
        return QWidget::eventFilter(watched, event);
    }

private:
    static bool isTextProducer(Mlt::Producer *producer)
    {
        if (!producer || !producer->is_valid())
            return false;
        const QString service = QString::fromUtf8(producer->get("mlt_service"));
        // AI imports and native generators can rebuild a color producer without
        // our optional presentation tag. Their standard text filter stays editable.
        return producer->get_int("shotcut:studioText") || service == QStringLiteral("color")
            || service == QStringLiteral("colour");
    }
    QAction *makeAction(const QString &name, const QString &title, const std::function<void()> &fn)
    {
        auto a = new QAction(title, this);
        a->setObjectName(name);
        m_window->addAction(a);
        Actions.add(name, a, tr("Text"));
        connect(a, &QAction::triggered, this, fn);
        return a;
    }
    void updateState()
    {
        const bool ready = !m_text->toPlainText().trimmed().isEmpty();
        m_add->setEnabled(ready);
        m_apply->setEnabled(ready && m_editTrack >= 0);
        m_primary->setEnabled(ready);
        m_primary->setText(m_editTrack >= 0 ? tr("Apply changes") : tr("Add text to video"));
        m_context->setText(m_editTrack >= 0 ? tr("Editing selected text") : tr("New text · starts at the playhead"));
        m_duration->setToolTip(m_editTrack >= 0 ? tr("How long this text stays on screen (Apply changes)")
                                                : tr("How long the new text stays on screen"));
        updatePreview();
    }
    void updatePreview()
    {
        m_preview->setText(m_text->toPlainText().isEmpty() ? tr("Your text") : m_text->toPlainText());
        const int id = m_styles->checkedId();
        m_preview->setAlignment((m_position->currentIndex() == 1 ? Qt::AlignBottom : m_position->currentIndex() == 2 ? Qt::AlignTop : Qt::AlignVCenter)
                                | (id == 1 ? Qt::AlignLeft : Qt::AlignHCenter));
        m_preview->setStyleSheet(QStringLiteral("QLabel { background: #11181b; color: #ffffff; border: 1px solid #344247; border-radius: 9px; padding: 12px; font-size: %1px; font-weight: 600; }").arg(id == 0 ? 23 : 17));
    }
    void fitText(Mlt::Filter &filter, int desired)
    {
        QFont font(QString::fromUtf8(filter.get("family")));
        font.setWeight(QFont::Weight(filter.get_int("weight")));
        font.setPixelSize(desired);
        const QFontMetricsF metrics(font);
        qreal width = 1;
        const auto lines = m_text->toPlainText().split(QLatin1Char('\n'));
        for (const auto &line : lines)
            width = qMax(width, metrics.horizontalAdvance(line));
        const auto bounds = filter.anim_get_rect("geometry", 0);
        const qreal fit = qMin(1.0, qMin((bounds.w - 12) / width,
            (bounds.h - 12) / (metrics.lineSpacing() * lines.size())));
        const int size = qMax(12, qFloor(desired * fit));
        filter.set("size", size);
        filter.set("shotcut:pointSize", size * .75);
    }
    void configure(Mlt::Filter &filter, int in, int out, bool preserve = false)
    {
        const int id = m_styles->checkedId();
        const int position = m_position->currentIndex();
        const auto &p = MLT.profile();
        const int h = qRound(p.height() * .22);
        const int y = qRound(p.height() * (position == 1 ? .71 : position == 2 ? .07 : .39));
        const auto words = m_text->toPlainText().replace(QStringLiteral("#"), QStringLiteral("\\#"));
        filter.set("argument", words.toUtf8().constData());
        if (preserve && !m_styleDirty) {
            if (m_positionDirty) {
                filter.set("geometry", QStringLiteral("%1 %2 %3 %4 1").arg(qRound(p.width() * .08)).arg(y).arg(qRound(p.width() * .84)).arg(h).toUtf8().constData());
                filter.set("shotcut:studioPosition", position);
            }
            if (filter.get_int("shotcut:studioAutoFit"))
                fitText(filter, filter.get_int("size"));
            return;
        }
        filter.set(kShotcutFilterProperty, "dynamicText");
        filter.set("argument", words.toUtf8().constData());
        filter.set("family", "Segoe UI");
        filter.set("size", qMax(24, qRound(p.height() * (id == 0 ? .050 : .036))));
        filter.set("shotcut:usePointSize", 1);
        filter.set("shotcut:pointSize", filter.get_int("size") * .75);
        filter.set("weight", id == 0 ? QFont::Bold : QFont::DemiBold);
        filter.set("style", "normal");
        filter.set("fgcolour", "#ffffffff");
        filter.set("bgcolour", "#00000000");
        filter.set("olcolour", "#c0000000");
        filter.set("outline", 2);
        filter.set("geometry", QStringLiteral("%1 %2 %3 %4 1").arg(qRound(p.width() * .08)).arg(y).arg(qRound(p.width() * .84)).arg(h).toUtf8().constData());
        filter.set("halign", id == 1 ? "left" : "center");
        filter.set("valign", "middle");
        filter.set("shotcut:studioStyle", id);
        filter.set("shotcut:studioPosition", position);
        filter.set("shotcut:studioAutoFit", 1);
        fitText(filter, filter.get_int("size"));
        filter.set_in_and_out(in, out);
    }
    void addText()
    {
        if (m_text->toPlainText().trimmed().isEmpty())
            return;
        auto tl = m_window->timelineDock();
        auto model = tl->model();
        if (!model->tractor()) {
            m_context->setText(tr("Add a video to the timeline first, then add your text."));
            return;
        }
        const int start = qMax(0, tl->position());
        const int frames = qMax(1, qRound(m_duration->value() * MLT.profile().fps()));
        Mlt::Producer producer(MLT.profile(), "color:");
        producer.set("resource", "#00000000");
        producer.set("mlt_image_format", "rgba");
        MLT.setDurationFromDefault(&producer);
        producer.set_in_and_out(0, frames - 1);
        producer.set("shotcut:studioText", 1);
        producer.set(kShotcutCaptionProperty, m_text->toPlainText().simplified().left(60).toUtf8().constData());
        Mlt::Filter filter(MLT.profile(), "dynamictext");
        if (!producer.is_valid() || !filter.is_valid()) {
            m_context->setText(tr("The text renderer is unavailable in this build."));
            return;
        }
        configure(filter, 0, frames - 1);
        producer.attach(filter);
        int target = -1;
        for (int t = 0; t < model->trackList().size(); ++t) {
            if (model->trackList()[t].type != VideoTrackType || tl->isTrackLocked(t)
                || model->getTrackName(t) != tr("Text"))
                continue;
            bool free = true;
            for (int c = 0; c < model->rowCount(model->index(t)); ++c) {
                auto info = model->getClipInfo(t, c);
                if (info && !info->producer->is_blank() && info->start < start + frames
                    && info->start + info->frame_count > start) {
                    free = false;
                    break;
                }
            }
            if (free) { target = t; break; }
        }
        m_busy = true;
        m_window->undoStack()->beginMacro(tr("Add text to video"));
        if (target < 0) {
            target = tl->addVideoTrack();
            tl->setTrackName(target, tr("Text"));
        }
        tl->overwrite(target, start, MLT.XML(&producer), false);
        m_window->undoStack()->endMacro();
        int clip = 0;
        for (; clip < model->rowCount(model->index(target)); ++clip) {
            auto info = model->getClipInfo(target, clip);
            if (info && info->start == start && !info->producer->is_blank())
                break;
        }
        m_busy = false;
        tl->setSelection({QPoint(clip, target)});
        m_window->seekTimeline(start);
        readSelection();
    }
    void applyText()
    {
        auto tl = m_window->timelineDock();
        if (m_editTrack < 0 || tl->isTrackLocked(m_editTrack))
            return;
        auto info = tl->model()->getClipInfo(m_editTrack, m_editClip);
        if (!info || !isTextProducer(info->producer))
            return;
        Mlt::Producer clone(MLT.profile(), "xml-string", MLT.XML(info->producer).toUtf8().constData());
        clone.set_in_and_out(info->frame_in, info->frame_out);
        for (int i = 0; i < clone.filter_count(); ++i) {
            std::unique_ptr<Mlt::Filter> filter(clone.filter(i));
            if (filter && QString::fromUtf8(filter->get(kShotcutFilterProperty)) == QStringLiteral("dynamicText")) {
                configure(*filter, info->frame_in, info->frame_out, true);
                break;
            }
        }
        clone.set(kShotcutCaptionProperty, m_text->toPlainText().simplified().left(60).toUtf8().constData());
        const QPoint selection(m_editClip, m_editTrack);
        int frames = qMax(1, qRound(m_duration->value() * MLT.profile().fps()));
        if (frames != info->frame_count) {
            // a new length: as long as asked, up to the next clip on this track
            auto *model = tl->model();
            QString note;
            for (int c = m_editClip + 1; c < model->rowCount(model->index(m_editTrack)); ++c) {
                auto next = model->getClipInfo(m_editTrack, c);
                if (next && !next->producer->is_blank()) {
                    if (next->start - info->start < frames) {
                        frames = next->start - info->start;
                        note = tr("Made it as long as fits before the next text (%1 s).")
                                   .arg(frames / MLT.profile().fps(), 0, 'f', 1);
                    }
                    break;
                }
            }
            clone.set("length", info->frame_in + frames);
            clone.set_in_and_out(info->frame_in, info->frame_in + frames - 1);
            for (int i = 0; i < clone.filter_count(); ++i) {
                std::unique_ptr<Mlt::Filter> filter(clone.filter(i));
                if (filter && QString::fromUtf8(filter->get(kShotcutFilterProperty)) == QStringLiteral("dynamicText"))
                    filter->set_in_and_out(info->frame_in, info->frame_in + frames - 1);
            }
            const int start = info->start;
            m_busy = true;
            tl->setSelection();
            m_window->undoStack()->beginMacro(tr("Edit text"));
            m_window->undoStack()->push(new Timeline::LiftCommand(*model, m_editTrack, m_editClip));
            tl->overwrite(m_editTrack, start, MLT.XML(&clone), false);
            m_window->undoStack()->endMacro();
            int clip = 0;
            for (; clip < model->rowCount(model->index(m_editTrack)); ++clip) {
                auto c = model->getClipInfo(m_editTrack, clip);
                if (c && c->start == start && !c->producer->is_blank())
                    break;
            }
            tl->setSelection({QPoint(clip, m_editTrack)});
            m_busy = false;
            readSelection();
            if (!note.isEmpty())
                m_context->setText(note);
            return;
        }
        auto cmd = new Timeline::UpdateCommand(*tl, m_editTrack, m_editClip, info->start);
        cmd->setXmlAfter(MLT.XML(&clone));
        cmd->setText(tr("Edit text"));
        m_busy = true;
        tl->setSelection();
        m_window->undoStack()->push(cmd);
        tl->setSelection({selection});
        m_busy = false;
        readSelection();
    }
    MainWindow *m_window;
    QPlainTextEdit *m_text;
    QButtonGroup *m_styles;
    QComboBox *m_position;
    QDoubleSpinBox *m_duration;
    QLabel *m_preview;
    QLabel *m_context;
    QLabel *m_intro;
    QLabel *m_hint;
    QWidget *m_viewport{nullptr};
    QPushButton *m_primary;
    QPushButton *m_new;
    QAction *m_add;
    QAction *m_apply;
    int m_editTrack{-1}, m_editClip{-1};
    bool m_busy{false};
    bool m_styleDirty{false}, m_positionDirty{false};
};
#endif
