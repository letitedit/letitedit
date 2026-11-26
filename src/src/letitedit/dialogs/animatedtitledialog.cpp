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

// Animated title: a title made from a few words, drawn by the AI.
// (Split out of lefeatures.cpp; what it shares with it is in featurehelpers.h.)

#include "featurehelpers.h"

namespace LeFeatures {

namespace {

struct TitleField
{
    QString key;
    QString label;
    bool lines = false;  // one per line (a list)
    bool number = false; // a number
};

struct TitleBlock
{
    QString name;
    QString label;
    QList<TitleField> fields;
};

QList<TitleBlock> titleBlocks()
{
    using F = TitleField;
    return {
        {QStringLiteral("title"), QObject::tr("Title"),
         {F{"title", QObject::tr("Big words")}, F{"subtitle", QObject::tr("Smaller line under it")},
          F{"kicker", QObject::tr("Small line above it")}}},
        {QStringLiteral("lower_third"), QObject::tr("Name and role"),
         {F{"name", QObject::tr("Name")}, F{"role", QObject::tr("Role or place")}}},
        {QStringLiteral("location"), QObject::tr("Place name"),
         {F{"place", QObject::tr("Place")}, F{"detail", QObject::tr("Detail (optional)")}}},
        {QStringLiteral("chapter"), QObject::tr("Chapter card"),
         {F{"number", QObject::tr("Number")}, F{"title", QObject::tr("Chapter name")},
          F{"kicker", QObject::tr("Small word above it")}}},
        {QStringLiteral("kinetic_quote"), QObject::tr("Quote that pops in"),
         {F{"text", QObject::tr("Quote")}, F{"attribution", QObject::tr("Who said it (optional)")}}},
        {QStringLiteral("count_up"), QObject::tr("Number that counts up"),
         {F{"to", QObject::tr("Counts up to"), false, true}, F{"prefix", QObject::tr("Before the number (e.g. $)")},
          F{"suffix", QObject::tr("After the number (e.g. km)")}, F{"label", QObject::tr("Words under it")}}},
        {QStringLiteral("callout"), QObject::tr("Label with a ring"), {F{"text", QObject::tr("Label")}}},
        {QStringLiteral("steps"), QObject::tr("Steps checklist"),
         {F{"title", QObject::tr("Title (optional)")}, F{"steps", QObject::tr("Steps, one per line"), true}}},
        {QStringLiteral("subscribe"), QObject::tr("Subscribe button"),
         {F{"text", QObject::tr("Button words")}, F{"handle", QObject::tr("Your channel name (optional)")}}},
        {QStringLiteral("end_card"), QObject::tr("End card"),
         {F{"title", QObject::tr("Big words")}, F{"cta", QObject::tr("Watch-next line")},
          F{"handle", QObject::tr("Your channel name (optional)")}}},
        {QStringLiteral("stinger"), QObject::tr("Quick wipe between parts"), {F{"text", QObject::tr("Words on it (optional)")}}},
    };
}

class AnimatedTitleDialog : public QDialog
{
public:
    explicit AnimatedTitleDialog(MainWindow *window)
        : QDialog(window)
        , m_window(window)
    {
        setObjectName(QStringLiteral("animatedTitleDialog"));
        setWindowTitle(tr("Animated title"));
        setMinimumSize(820, 560);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        column->addWidget(headingLabel(tr("Add an animated title"), this));
        column->addWidget(mutedLabel(tr("Pick a kind, type your words and look at the preview. Add at playhead puts it "
                                        "on a Titles track over your video, in this video's style colours and fonts. "
                                        "It's drawn on this computer."),
                                     this));
        auto middle = new QHBoxLayout;
        middle->setSpacing(14);
        m_list = new QListWidget(this);
        m_list->setObjectName(QStringLiteral("animatedTitleBlocks"));
        m_list->setFixedWidth(210);
        middle->addWidget(m_list);
        auto right = new QVBoxLayout;
        m_about = mutedLabel(QString(), this);
        m_about->setObjectName(QStringLiteral("animatedTitleAbout"));
        right->addWidget(m_about);
        m_formHolder = new QWidget(this);
        m_form = new QFormLayout(m_formHolder);
        m_form->setContentsMargins(0, 0, 0, 0);
        right->addWidget(m_formHolder);
        auto lengthRow = new QHBoxLayout;
        lengthRow->addWidget(new QLabel(tr("On screen for"), this));
        m_seconds = new QDoubleSpinBox(this);
        m_seconds->setObjectName(QStringLiteral("animatedTitleSeconds"));
        m_seconds->setRange(1.0, 20.0);
        m_seconds->setDecimals(1);
        m_seconds->setSingleStep(0.5);
        m_seconds->setSuffix(tr(" seconds"));
        lengthRow->addWidget(m_seconds);
        lengthRow->addStretch(1);
        m_previewButton = new QPushButton(tr("Show preview"), this);
        m_previewButton->setObjectName(QStringLiteral("animatedTitlePreviewButton"));
        connect(m_previewButton, &QPushButton::clicked, this, [this]() { preview(); });
        lengthRow->addWidget(m_previewButton);
        right->addLayout(lengthRow);
        m_preview = new QLabel(this);
        m_preview->setObjectName(QStringLiteral("animatedTitlePreview"));
        m_preview->setAlignment(Qt::AlignCenter);
        m_preview->setMinimumHeight(220);
        m_preview->setStyleSheet(QStringLiteral("background: %1; border-radius: 8px;").arg(LetItEditColors::deep));
        m_preview->setText(tr("The preview shows here"));
        right->addWidget(m_preview, 1);
        middle->addLayout(right, 1);
        column->addLayout(middle, 1);
        m_run = new RunBox(this, QStringLiteral("animatedTitle"));
        column->addWidget(m_run);
        auto buttons = new QHBoxLayout;
        auto close = new QPushButton(tr("Close"), this);
        close->setObjectName(QStringLiteral("animatedTitleClose"));
        connect(close, &QPushButton::clicked, this, &QDialog::reject);
        m_stop = new QPushButton(tr("Stop"), this);
        m_stop->setObjectName(QStringLiteral("animatedTitleStop"));
        m_stop->hide();
        connect(m_stop, &QPushButton::clicked, this, [this]() { m_run->run->cancel(); });
        m_add = new QPushButton(tr("Add at playhead"), this);
        m_add->setObjectName(QStringLiteral("animatedTitleAdd"));
        m_add->setProperty("studioPrimary", true);
        connect(m_add, &QPushButton::clicked, this, [this]() { add(); });
        buttons->addWidget(close);
        buttons->addStretch(1);
        buttons->addWidget(m_stop);
        buttons->addWidget(m_add);
        column->addLayout(buttons);

        for (const auto &b : titleBlocks()) {
            auto item = new QListWidgetItem(b.label, m_list);
            item->setData(Qt::UserRole, b.name);
        }
        connect(m_list, &QListWidget::currentRowChanged, this, [this](int) { fill(); });
        m_add->setEnabled(false);
        m_previewButton->setEnabled(false);
        m_run->done = [this](bool ok, const QJsonObject &result, const QString &why) { finished(ok, result, why); };
        m_stage = QStringLiteral("blocks");
        m_run->start(QStringLiteral("motion-blocks"), {}, false, QString(), tr("Getting the titles ready..."));
    }

    void reject() override
    {
        if (m_run->running())
            m_run->run->cancel();
        QDialog::reject();
    }

    QJsonObject qaState() const
    {
        return QJsonObject{{"visible", isVisible()}, {"running", m_run->running()}, {"stage", m_stage},
                           {"status", m_run->status->text()}, {"block", currentBlock()},
                           {"previewed", !m_preview->pixmap().isNull()}, {"blocks", m_list->count()},
                           {"fields", m_fields.size()}, {"added", m_added}};
    }

private:
    QString currentBlock() const
    {
        return m_list->currentItem() ? m_list->currentItem()->data(Qt::UserRole).toString() : QString();
    }

    void fill()
    {
        while (m_form->rowCount())
            m_form->removeRow(0);
        m_fields.clear();
        const QString name = currentBlock();
        const QJsonObject block = m_blocks.value(name).toObject();
        const QJsonObject defaults = block.value("params").toObject();
        m_about->setText(block.value("about").toString());
        m_seconds->setValue(block.value("duration").toDouble(4.0));
        for (const auto &b : titleBlocks()) {
            if (b.name != name)
                continue;
            for (const auto &f : b.fields) {
                QWidget *editor = nullptr;
                const QJsonValue d = defaults.value(f.key);
                if (f.lines) {
                    auto e = new QPlainTextEdit(m_formHolder);
                    QStringList lines;
                    for (const auto &v : d.toArray())
                        lines << v.toString();
                    e->setPlainText(lines.join(QLatin1Char('\n')));
                    e->setFixedHeight(80);
                    editor = e;
                } else {
                    auto e = new QLineEdit(m_formHolder);
                    e->setText(d.isDouble() ? QString::number(d.toDouble()) : d.toString());
                    connect(e, &QLineEdit::returnPressed, this, [this]() { preview(); });
                    editor = e;
                }
                editor->setObjectName(QStringLiteral("animatedTitleField_%1").arg(f.key));
                editor->setProperty("leKey", f.key);
                editor->setProperty("leLines", f.lines);
                editor->setProperty("leNumber", f.number);
                m_form->addRow(f.label, editor);
                m_fields << editor;
            }
        }
        m_preview->setPixmap(QPixmap());
        m_preview->setText(tr("Press Show preview to see it"));
    }

    // {block, params, duration} from the fields
    QJsonObject spec(QString *why) const
    {
        QJsonObject params;
        for (auto e : m_fields) {
            const QString key = e->property("leKey").toString();
            if (e->property("leLines").toBool()) {
                QJsonArray lines;
                for (const auto &l : static_cast<QPlainTextEdit *>(e)->toPlainText().split(QLatin1Char('\n'), Qt::SkipEmptyParts))
                    lines.append(l.trimmed());
                params.insert(key, lines);
            } else if (e->property("leNumber").toBool()) {
                bool ok = false;
                const double v = static_cast<QLineEdit *>(e)->text().trimmed().replace(QLatin1Char(','), QString()).toDouble(&ok);
                if (!ok) {
                    *why = tr("Type a number for “%1”.").arg(m_form->labelForField(e) ? static_cast<QLabel *>(m_form->labelForField(e))->text() : key);
                    return {};
                }
                params.insert(key, v);
            } else {
                params.insert(key, static_cast<QLineEdit *>(e)->text().trimmed());
            }
        }
        if (m_fields.size() && !m_fields.first()->property("leLines").toBool()
            && !m_fields.first()->property("leNumber").toBool()
            && static_cast<QLineEdit *>(m_fields.first())->text().trimmed().isEmpty()
            && currentBlock() != QLatin1String("stinger")) {
            *why = tr("Type the words first.");
            return {};
        }
        return QJsonObject{{"block", currentBlock()}, {"params", params}, {"duration", m_seconds->value()}};
    }

    QStringList sizeArgs() const
    {
        const int w = MLT.profile().width(), h = MLT.profile().height();
        const double fps = MLT.profile().fps();
        QStringList args{QStringLiteral("--size"), QString::number(w > 0 ? w : 1920), QString::number(h > 0 ? h : 1080),
                         QStringLiteral("--fps"), QString::number(fps > 0 ? fps : 30.0)};
        const QString style = MyStyle::projectStyle(m_window);
        if (!style.isEmpty())
            args << QStringLiteral("--look") << style;
        return args;
    }

    void preview()
    {
        if (m_run->running())
            return;
        QString why;
        const QJsonObject s = spec(&why);
        if (s.isEmpty()) {
            m_run->say(why, true);
            return;
        }
        m_stage = QStringLiteral("preview");
        setBusy(true);
        m_run->start(QStringLiteral("motion-preview"),
                     QStringList{QStringLiteral("--spec"), QString::fromUtf8(QJsonDocument(s).toJson(QJsonDocument::Compact)),
                                 QStringLiteral("--count"), QStringLiteral("3")}
                         + sizeArgs(),
                     false, QString(), tr("Drawing the preview (a few seconds)..."));
    }

    void add()
    {
        if (m_run->running())
            return;
        if (!m_window->multitrack()) {
            m_run->say(tr("Put a video on the timeline first, then add the title."), true);
            return;
        }
        QString why;
        const QJsonObject s = spec(&why);
        if (s.isEmpty()) {
            m_run->say(why, true);
            return;
        }
        const QString project = m_window->fileName();
        const QString out = project.isEmpty() ? Settings.appDataLocation() + QStringLiteral("/made")
                                              : QFileInfo(project).absolutePath() + QStringLiteral("/made");
        m_stage = QStringLiteral("render");
        setBusy(true);
        m_run->start(QStringLiteral("motion-render"),
                     QStringList{QStringLiteral("--spec"), QString::fromUtf8(QJsonDocument(s).toJson(QJsonDocument::Compact)),
                                 QStringLiteral("--out-dir"), out}
                         + sizeArgs(),
                     true, QStringLiteral("letitedit animated title"), tr("Making the title..."));
    }

    void setBusy(bool busy)
    {
        m_add->setEnabled(!busy && m_engineReady);
        m_previewButton->setEnabled(!busy && m_engineReady);
        m_list->setEnabled(!busy);
        m_stop->setVisible(busy && m_stage == QLatin1String("render"));
    }

    void finished(bool ok, const QJsonObject &result, const QString &why)
    {
        const QString stage = m_stage;
        m_stage.clear();
        if (stage == QLatin1String("blocks")) {
            m_blocks = result.value("blocks").toObject();
            const QString engine = result.value("engine").toString();
            m_engineReady = ok && engine == QLatin1String("ready");
            for (int i = m_list->count() - 1; i >= 0; --i)
                if (!m_blocks.contains(m_list->item(i)->data(Qt::UserRole).toString()))
                    delete m_list->takeItem(i);
            m_list->setCurrentRow(0);
            setBusy(false);
            if (!ok)
                m_run->say(tr("The titles couldn't be loaded: %1").arg(why), true);
            else if (!m_engineReady)
                m_run->say(tr("Animated titles need the motion engine, which isn't on this computer yet (%1).")
                               .arg(engine),
                           true);
            else
                m_run->say(QString());
            return;
        }
        setBusy(false);
        if (!ok) {
            m_run->say(why.isEmpty() ? tr("Stopped.") : tr("That didn't work: %1").arg(why), !why.isEmpty());
            return;
        }
        if (stage == QLatin1String("preview")) {
            const QPixmap sheet(result.value("sheet").toString());
            if (sheet.isNull()) {
                m_run->say(tr("The preview couldn't be shown."), true);
                return;
            }
            m_preview->setPixmap(sheet.scaled(m_preview->size() - QSize(12, 12), Qt::KeepAspectRatio, Qt::SmoothTransformation));
            m_run->say(tr("The preview shows three moments of it. Change the words and press Show preview again, or "
                          "Add at playhead."));
            return;
        }
        // rendered: on a Titles track at the playhead, one undo step
        const QString file = result.value("file").toString();
        QString problem;
        const QString xml = producerXml(file, false, QString(), 0, 0, &problem);
        const QString label = m_list->currentItem() ? m_list->currentItem()->text() : tr("title");
        if (xml.isEmpty() || !placeAtPlayhead(m_window, xml, false, tr("Titles"),
                                              tr("Add an animated title: %1").arg(label), &problem)) {
            m_run->say(problem, true);
            return;
        }
        m_added = true;
        m_run->say(tr("Added at the playhead on the Titles track. Undo takes it back."));
        m_window->showStatusMessage(tr("Animated title added (one Undo step)."), 8);
    }

    MainWindow *m_window;
    QListWidget *m_list = nullptr;
    QLabel *m_about = nullptr;
    QWidget *m_formHolder = nullptr;
    QFormLayout *m_form = nullptr;
    QList<QWidget *> m_fields;
    QDoubleSpinBox *m_seconds = nullptr;
    QPushButton *m_previewButton = nullptr;
    QLabel *m_preview = nullptr;
    RunBox *m_run = nullptr;
    QPushButton *m_stop = nullptr;
    QPushButton *m_add = nullptr;
    QJsonObject m_blocks;
    QString m_stage;
    bool m_engineReady = false;
    bool m_added = false;
};

} // namespace

void showAnimatedTitle(MainWindow *window)
{
    AnimatedTitleDialog dialog(window);
    dialog.exec();
}

void addAnimatedTitleState(QJsonObject &out)
{
    if (auto d = openDialog<AnimatedTitleDialog>(QStringLiteral("animatedTitleDialog")))
        out.insert("animated_title", d->qaState());
}

} // namespace LeFeatures
