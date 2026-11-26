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

#include "letitedit/panels/myassets.h"

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "letitedit/workspace/focusworkspace.h"
#include "letitedit/letitedit.h"
#include "mainwindow.h"

#include <QComboBox>
#include <QDesktopServices>
#include <QDialog>
#include <QDir>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMimeData>
#include <QPainter>
#include <QPixmap>
#include <QPointer>
#include <QPushButton>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>

namespace MyAssets {

namespace {

QString pythonExe()
{
    return aiChatSettings().value("python").toString();
}

// python bridge/my_assets.py <args> -> its JSON (empty on failure; why, if asked). The helper reads the folder named by
// LETITEDIT_MY_ASSETS or settings.json, the same one the AI's tool reads.
QJsonObject run(const QStringList &args, QString *why = nullptr, int timeoutMs = 180000)
{
    QByteArray printed;
    const bool ok = !pythonExe().isEmpty()
                    && leRun(pythonExe(),
                             QStringList{aiRootPath(QStringLiteral("bridge/my_assets.py"))} + args,
                             nullptr,
                             &printed,
                             timeoutMs);
    const int brace = printed.indexOf('{');
    const QJsonObject out = brace >= 0 ? QJsonDocument::fromJson(printed.mid(brace)).object() : QJsonObject();
    if (why && (!ok || out.isEmpty() || out.contains("error"))) {
        *why = out.value("error").toString();
        if (why->isEmpty()) {
            QStringList lines = QString::fromUtf8(printed).split(QLatin1Char('\n'), Qt::SkipEmptyParts);
            *why = lines.isEmpty() ? QObject::tr("the My assets helper did not answer")
                                   : lines.last().trimmed().left(240);
        }
    }
    return (ok && !out.contains("error")) ? out : QJsonObject();
}

QString kindWord(const QString &kind)
{
    static const QHash<QString, QString> words{{"logo", QObject::tr("Logo")},
                                               {"intro", QObject::tr("Intro")},
                                               {"outro", QObject::tr("Outro")},
                                               {"clip", QObject::tr("Clip")},
                                               {"sound", QObject::tr("Sound")},
                                               {"picture", QObject::tr("Picture")},
                                               {"font", QObject::tr("Font")},
                                               {"colours", QObject::tr("Colors")}};
    return words.value(kind, kind);
}

QString seconds(double s)
{
    return s < 60 ? QObject::tr("%1 s").arg(s, 0, 'f', 1)
                  : QObject::tr("%1 min %2 s").arg(int(s) / 60).arg(int(s) % 60);
}

// A small picture for an item: its own thumbnail, else a drawn one (colour stripes, a note, "Aa").
QIcon iconFor(const QJsonObject &item)
{
    const int size = 72;
    QPixmap pix(size, size);
    pix.fill(QColor(LetItEditColors::raised));
    const QString thumb = item.value("thumb").toString();
    QPainter p(&pix);
    p.setRenderHint(QPainter::Antialiasing);
    if (!thumb.isEmpty() && QFileInfo::exists(thumb)) {
        QPixmap t(thumb);
        if (!t.isNull()) {
            t = t.scaled(size, size, Qt::KeepAspectRatio, Qt::SmoothTransformation);
            p.drawPixmap((size - t.width()) / 2, (size - t.height()) / 2, t);
            return QIcon(pix);
        }
    }
    const QString kind = item.value("kind").toString();
    if (kind == QLatin1String("colours")) {
        QStringList hexes;
        for (const auto &v : item.value("colour_list").toArray())
            hexes << v.toString();
        const int n = qMax(1, qMin(6, int(hexes.size())));
        for (int i = 0; i < n && i < hexes.size(); ++i)
            p.fillRect(QRect(0, i * size / n, size, size / n + 1), QColor(hexes[i]));
    } else {
        p.setPen(QColor(LetItEditColors::cream));
        QFont f = p.font();
        f.setPixelSize(kind == QLatin1String("font") ? 30 : 34);
        f.setBold(true);
        p.setFont(f);
        p.drawText(QRect(0, 0, size, size),
                   Qt::AlignCenter,
                   kind == QLatin1String("sound") ? QString(QChar(0x266A)) : QStringLiteral("Aa"));
    }
    return QIcon(pix);
}

class MyAssetsPanel : public QDialog
{
public:
    explicit MyAssetsPanel(MainWindow *window)
        : QDialog(window)
    {
        using namespace LetItEditColors;
        setObjectName(QStringLiteral("myAssetsDialog"));
        setWindowTitle(tr("My assets"));
        setMinimumSize(640, 560);
        setAcceptDrops(true);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        auto intro = new QLabel(tr("A place to keep your own logo, intro, outro, colors, clips, sounds and fonts. Drop files "
                                   "here. Keeping something here doesn't mean a video will use it, and you never have to "
                                   "add anything."),
                                this);
        intro->setWordWrap(true);
        column->addWidget(intro);

        auto top = new QHBoxLayout;
        auto add = new QPushButton(tr("Add files..."), this);
        add->setObjectName(QStringLiteral("myAssetsAdd"));
        add->setToolTip(tr("Copies the files you pick into My assets. Your originals are never changed."));
        connect(add, &QPushButton::clicked, this, [this]() { pickFiles(); });
        top->addWidget(add);
        auto open = new QPushButton(tr("Open folder"), this);
        open->setObjectName(QStringLiteral("myAssetsOpenFolder"));
        open->setToolTip(tr("Shows the My assets folder: you can also drop files into it yourself"));
        connect(open, &QPushButton::clicked, this, [this]() {
            if (m_folder.isEmpty())
                return;
            QDir().mkpath(m_folder);
            QDesktopServices::openUrl(QUrl::fromLocalFile(m_folder));
        });
        top->addWidget(open);
        top->addStretch(1);
        column->addLayout(top);

        m_folderLabel = new QLabel(this);
        m_folderLabel->setObjectName(QStringLiteral("myAssetsFolder"));
        m_folderLabel->setProperty("studioMuted", true);
        m_folderLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
        m_folderLabel->setWordWrap(true);
        column->addWidget(m_folderLabel);

        m_colours = new QLabel(this);
        m_colours->setObjectName(QStringLiteral("myAssetsColours"));
        m_colours->setTextFormat(Qt::RichText);
        column->addWidget(m_colours);

        m_empty = new QLabel(tr("Nothing here yet. Drop a logo, an outro, a clip or a sound on this window, or press Add "
                                "files. letitedit works fine without any."),
                             this);
        m_empty->setObjectName(QStringLiteral("myAssetsEmpty"));
        m_empty->setWordWrap(true);
        m_empty->setAlignment(Qt::AlignCenter);
        m_empty->setMinimumHeight(120);
        m_empty->setStyleSheet(
            QStringLiteral("color: %1; border: 1px dashed %2; border-radius: 8px;").arg(muted, line));
        column->addWidget(m_empty, 1);

        m_list = new QListWidget(this);
        m_list->setObjectName(QStringLiteral("myAssetsList"));
        m_list->setIconSize(QSize(72, 72));
        m_list->setSpacing(2);
        m_list->setSelectionMode(QAbstractItemView::SingleSelection);
        column->addWidget(m_list, 1);
        connect(m_list, &QListWidget::currentItemChanged, this, [this]() { showSelected(); });

        // The chosen item
        m_detail = new QWidget(this);
        m_detail->setObjectName(QStringLiteral("myAssetsDetail"));
        auto detail = new QVBoxLayout(m_detail);
        detail->setContentsMargins(0, 0, 0, 0);
        detail->setSpacing(6);
        m_what = new QLabel(m_detail);
        m_what->setObjectName(QStringLiteral("myAssetsWhat"));
        m_what->setWordWrap(true);
        detail->addWidget(m_what);
        m_note = new QLineEdit(m_detail);
        m_note->setObjectName(QStringLiteral("myAssetsNote"));
        m_note->setPlaceholderText(tr("A note about this one (optional)"));
        m_note->setMaxLength(300);
        connect(m_note, &QLineEdit::textChanged, this, [this]() {
            if (!m_filling)
                m_noteTimer.start();
        });
        detail->addWidget(m_note);
        auto row = new QHBoxLayout;
        row->addWidget(new QLabel(tr("This is a"), m_detail));
        m_kind = new QComboBox(m_detail);
        m_kind->setObjectName(QStringLiteral("myAssetsKind"));
        m_kind->setToolTip(tr("letitedit works out what each one is. Change it here if it got it wrong."));
        row->addWidget(m_kind);
        row->addStretch(1);
        auto remove = new QPushButton(tr("Take out of My assets"), m_detail);
        remove->setObjectName(QStringLiteral("myAssetsRemove"));
        remove->setToolTip(tr("Moves the copy out of My assets (into a hidden folder inside it). Your original file "
                              "is never touched."));
        connect(remove, &QPushButton::clicked, this, [this]() { removeSelected(); });
        row->addWidget(remove);
        detail->addLayout(row);
        column->addWidget(m_detail);
        m_detail->hide();

        m_status = new QLabel(this);
        m_status->setObjectName(QStringLiteral("myAssetsStatus"));
        m_status->setWordWrap(true);
        m_status->setStyleSheet(QStringLiteral("color: %1;").arg(tealLight));
        column->addWidget(m_status);
        auto buttons = new QHBoxLayout;
        buttons->addStretch(1);
        auto close = new QPushButton(tr("Close"), this);
        close->setObjectName(QStringLiteral("myAssetsClose"));
        connect(close, &QPushButton::clicked, this, &QDialog::accept);
        buttons->addWidget(close);
        column->addLayout(buttons);

        m_noteTimer.setSingleShot(true);
        m_noteTimer.setInterval(600);
        connect(&m_noteTimer, &QTimer::timeout, this, [this]() { saveNote(); });
        m_kind->addItem(tr("Let letitedit decide"), QString());
        for (const char *k : {"logo", "intro", "outro", "clip", "sound", "picture", "font", "colours"})
            m_kind->addItem(kindWord(QString::fromLatin1(k)), QString::fromLatin1(k));
        connect(m_kind, &QComboBox::currentIndexChanged, this, [this]() {
            if (!m_filling)
                saveKind();
        });
        // what is there now: at once from what is already known, then with the new files looked at
        QTimer::singleShot(0, this, [this]() { refresh(); });
    }

    QJsonObject qaState() const
    {
        QJsonArray items;
        for (const auto &v : m_items) {
            const QJsonObject o = v.toObject();
            items.append(QJsonObject{{"id", o.value("id")},
                                     {"kind", o.value("kind")},
                                     {"kind_from", o.value("kind_from")},
                                     {"note", o.value("note")},
                                     {"text", o.value("text")},
                                     {"duration_s", o.value("duration_s")},
                                     {"measuring", o.value("measuring")},
                                     {"problem", o.value("problem")},
                                     {"thumb", o.value("thumb")}});
        }
        return QJsonObject{{"visible", isVisible()},
                           {"folder", m_folder},
                           {"count", int(m_items.size())},
                           {"items", items},
                           {"selected", m_selected},
                           {"note_field", m_note->text()},
                           {"kind_field", m_kind->currentData().toString()},
                           {"detail_visible", !m_detail->isHidden()},
                           {"empty_visible", !m_empty->isHidden()},
                           {"colours", QJsonArray::fromStringList(m_colourList)},
                           {"status", m_status->text()},
                           {"width", width()},
                           {"height", height()}};
    }

    void qaAdd(const QStringList &paths) { addFiles(paths); }
    void qaSelect(const QString &id)
    {
        for (int i = 0; i < m_list->count(); ++i)
            if (m_list->item(i)->data(Qt::UserRole).toString() == id)
                m_list->setCurrentRow(i);
    }

protected:
    void dragEnterEvent(QDragEnterEvent *event) override
    {
        if (event->mimeData()->hasUrls())
            event->acceptProposedAction();
    }
    void dropEvent(QDropEvent *event) override
    {
        QStringList paths;
        for (const QUrl &u : event->mimeData()->urls())
            if (u.isLocalFile())
                paths << u.toLocalFile();
        if (!paths.isEmpty()) {
            event->acceptProposedAction();
            addFiles(paths);
        }
    }
    void done(int r) override
    {
        flushNote();
        QDialog::done(r);
    }

private:
    QJsonObject current() const
    {
        for (const auto &v : m_items)
            if (v.toObject().value("id").toString() == m_selected)
                return v.toObject();
        return {};
    }

    void pickFiles()
    {
        const QStringList paths = QFileDialog::getOpenFileNames(
            this,
            tr("Add to My assets"),
            QString(),
            tr("Pictures, clips, sounds, fonts and color files (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.svg *.mp4 "
               "*.mov *.m4v *.mkv *.webm *.wav *.mp3 *.m4a *.flac *.aac *.ogg *.ttf *.otf *.txt *.json *.csv *.gpl);;"
               "All files (*)"));
        if (!paths.isEmpty())
            addFiles(paths);
    }

    void addFiles(const QStringList &paths)
    {
        flushNote();
        m_status->setText(tr("Copying %n file(s) into My assets...", "", paths.size()));
        QString why;
        const QJsonObject r = run(QStringList{QStringLiteral("add")} + paths, &why, 3600000);
        if (r.isEmpty()) {
            m_status->setText(tr("Could not add them: %1").arg(why));
            return;
        }
        const int added = r.value("added").toArray().size();
        QStringList notes;
        for (const auto &s : r.value("skipped").toArray())
            notes << tr("%1: %2").arg(QFileInfo(s.toObject().value("path").toString()).fileName(),
                                      s.toObject().value("why").toString());
        refresh();
        QString line = added ? tr("Added %n file(s).", "", added)
                             : tr("Nothing was added.");
        if (!notes.isEmpty())
            line += QLatin1Char(' ') + tr("Left out: %1.").arg(notes.join(QStringLiteral("; ")));
        m_status->setText(line);
    }

    void refresh(const QString &select = QString())
    {
        const QString keep = select.isEmpty() ? m_selected : select;
        QString why;
        QJsonObject r = run({QStringLiteral("list"), QStringLiteral("--quick")}, &why, 60000);
        if (r.isEmpty()) {
            m_status->setText(tr("Could not read My assets: %1").arg(why));
            return;
        }
        fill(r, keep);
        bool measuring = false;
        for (const auto &v : std::as_const(m_items))
            measuring = measuring || v.toObject().value("measuring").toBool();
        if (measuring) {
            m_status->setText(tr("Looking at your files..."));
            r = run({QStringLiteral("list")}, &why, 300000);
            if (!r.isEmpty()) {
                fill(r, keep);
                m_status->setText(QString());
            }
        }
    }

    void fill(const QJsonObject &r, const QString &keep)
    {
        m_filling = true;
        m_folder = r.value("folder").toString();
        m_items = r.value("items").toArray();
        m_colourList.clear();
        for (const auto &c : r.value("colours").toArray())
            m_colourList << c.toString();
        m_folderLabel->setText(tr("Folder: %1").arg(QDir::toNativeSeparators(m_folder)));
        QString swatches;
        for (const QString &c : std::as_const(m_colourList))
            swatches
                += QStringLiteral("<span style='background-color:%1;'>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>&nbsp;").arg(c);
        m_colours->setText(m_colourList.isEmpty() ? QString() : tr("Your colors: %1").arg(swatches));
        m_colours->setVisible(!m_colourList.isEmpty());
        m_list->clear();
        for (const auto &v : std::as_const(m_items)) {
            const QJsonObject o = v.toObject();
            const QString kind = o.value("kind").toString();
            QStringList facts{kindWord(kind)};
            if (o.contains("duration_s") && kind != QLatin1String("picture") && kind != QLatin1String("logo"))
                facts << seconds(o.value("duration_s").toDouble());
            if (o.contains("width"))
                facts << QStringLiteral("%1x%2").arg(o.value("width").toInt()).arg(o.value("height").toInt());
            if (o.value("has_alpha").toBool())
                facts << tr("transparent background");
            if (o.value("measuring").toBool())
                facts << tr("looking...");
            if (!o.value("problem").toString().isEmpty())
                facts << tr("can't be opened yet");
            QString text = o.value("name").toString() + QLatin1Char('\n') + facts.join(QStringLiteral(" - "));
            if (!o.value("note").toString().isEmpty())
                text += QLatin1Char('\n') + o.value("note").toString();
            auto item = new QListWidgetItem(iconFor(o), text, m_list);
            item->setData(Qt::UserRole, o.value("id").toString());
            item->setToolTip(o.value("text").toString() + QLatin1Char('\n') + o.value("path").toString());
            item->setSizeHint(QSize(0, 84));
        }
        m_empty->setVisible(m_items.isEmpty());
        m_list->setVisible(!m_items.isEmpty());
        int row = -1;
        for (int i = 0; i < m_list->count(); ++i)
            if (m_list->item(i)->data(Qt::UserRole).toString() == keep)
                row = i;
        m_selected.clear();
        m_filling = false;
        m_list->setCurrentRow(row);
        showSelected();
    }

    void showSelected()
    {
        const QListWidgetItem *it = m_list->currentItem();
        if (!m_filling && !m_selected.isEmpty() && it && it->data(Qt::UserRole).toString() != m_selected)
            flushNote();
        m_selected = it ? it->data(Qt::UserRole).toString() : QString();
        const QJsonObject o = current();
        m_detail->setVisible(!o.isEmpty());
        if (o.isEmpty())
            return;
        m_filling = true;
        m_what->setText(tr("letitedit sees: %1").arg(o.value("text").toString()));
        m_note->setText(o.value("note").toString());
        const QString kind = o.value("kind_from").toString() == QLatin1String("person") ? o.value("kind").toString()
                                                                                         : QString();
        m_kind->setCurrentIndex(qMax(0, m_kind->findData(kind)));
        m_filling = false;
    }

    void flushNote()
    {
        if (m_noteTimer.isActive()) {
            m_noteTimer.stop();
            saveNote();
        }
    }

    void saveNote()
    {
        if (m_selected.isEmpty())
            return;
        const QString id = m_selected;
        QString why;
        const QJsonObject r = run({QStringLiteral("note"), id, m_note->text().trimmed()}, &why, 60000);
        if (r.isEmpty()) {
            m_status->setText(tr("Could not save the note: %1").arg(why));
            return;
        }
        // keep the list's own copy in step without redrawing it under the person's cursor
        for (int i = 0; i < m_items.size(); ++i) {
            QJsonObject o = m_items[i].toObject();
            if (o.value("id").toString() == id) {
                o["note"] = r.value("note");
                o["text"] = r.value("text");
                m_items[i] = o;
            }
        }
        for (int i = 0; i < m_list->count(); ++i) {
            if (m_list->item(i)->data(Qt::UserRole).toString() != id)
                continue;
            const QStringList lines = m_list->item(i)->text().split(QLatin1Char('\n'));
            QString text = lines.value(0) + QLatin1Char('\n') + lines.value(1);
            if (!r.value("note").toString().isEmpty())
                text += QLatin1Char('\n') + r.value("note").toString();
            m_list->item(i)->setText(text);
        }
        m_status->setText(tr("Note saved."));
    }

    void saveKind()
    {
        if (m_selected.isEmpty())
            return;
        flushNote();
        QString why;
        const QString id = m_selected;
        const QJsonObject r = run({QStringLiteral("kind"), id, m_kind->currentData().toString()}, &why, 60000);
        if (r.isEmpty()) {
            m_status->setText(tr("Could not change it: %1").arg(why));
            return;
        }
        refresh(id);
        m_status->setText(tr("Saved."));
    }

    void removeSelected()
    {
        if (m_selected.isEmpty())
            return;
        flushNote();
        QString why;
        const QString name = m_selected;
        const QJsonObject r = run({QStringLiteral("remove"), name}, &why, 600000);
        if (r.isEmpty()) {
            m_status->setText(tr("Could not take it out: %1").arg(why));
            return;
        }
        m_selected.clear();
        refresh(QStringLiteral("-"));
        m_status->setText(
            tr("Took out \"%1\". The copy is kept in a hidden folder inside My assets; your original was not touched.")
                .arg(name));
    }

    QListWidget *m_list = nullptr;
    QLabel *m_folderLabel = nullptr;
    QLabel *m_colours = nullptr;
    QLabel *m_empty = nullptr;
    QWidget *m_detail = nullptr;
    QLabel *m_what = nullptr;
    QLineEdit *m_note = nullptr;
    QComboBox *m_kind = nullptr;
    QLabel *m_status = nullptr;
    QTimer m_noteTimer;
    QJsonArray m_items;
    QStringList m_colourList;
    QString m_folder;
    QString m_selected;
    bool m_filling = false;
};

QPointer<QDialog> &openPanel()
{
    static QPointer<QDialog> panel;
    return panel;
}

} // namespace

void show(MainWindow *window)
{
    MyAssetsPanel panel(window);
    openPanel() = &panel;
    panel.exec();
}

QJsonObject panelState()
{
    if (auto panel = static_cast<MyAssetsPanel *>(openPanel().data()))
        return panel->qaState();
    return QJsonObject{{"visible", false}};
}

void addToPanel(const QStringList &paths)
{
    if (auto panel = static_cast<MyAssetsPanel *>(openPanel().data()))
        QMetaObject::invokeMethod(panel, [panel, paths]() { panel->qaAdd(paths); }, Qt::QueuedConnection);
}

void selectInPanel(const QString &id)
{
    if (auto panel = static_cast<MyAssetsPanel *>(openPanel().data()))
        QMetaObject::invokeMethod(panel, [panel, id]() { panel->qaSelect(id); }, Qt::QueuedConnection);
}

} // namespace MyAssets
