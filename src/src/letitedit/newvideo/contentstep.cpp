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

// New video, step 2: Content (my footage, with the drive buttons and the folder browser, or 100% AI).
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

namespace {
// The check box on the right of each file (T176): drawn from the row's highlight, so the two can never disagree.
// Clicking the row or the box toggles both (the list is in MultiSelection); Space does the same from the keyboard.
class ChosenBoxDelegate : public QStyledItemDelegate
{
public:
    using QStyledItemDelegate::QStyledItemDelegate;
    void paint(QPainter *painter, const QStyleOptionViewItem &option, const QModelIndex &index) const override
    {
        QStyleOptionViewItem opt(option);
        initStyleOption(&opt, index);
        opt.features &= ~QStyleOptionViewItem::HasCheckIndicator;
        opt.text.clear();
        const QWidget *widget = option.widget;
        QStyle *style = widget ? widget->style() : QApplication::style();
        style->drawControl(QStyle::CE_ItemViewItem, &opt, painter, widget);
        const bool on = option.state & QStyle::State_Selected;
        const int side = 18;
        const QRectF box(option.rect.center().x() - side / 2.0 + 0.5, option.rect.center().y() - side / 2.0 + 0.5, side - 1, side - 1);
        painter->save();
        painter->setRenderHint(QPainter::Antialiasing);
        painter->setPen(QPen(on ? QColor(LetItEditColors::teal) : QColor(QStringLiteral("#8A949B")), 1.5));
        painter->setBrush(on ? QColor(LetItEditColors::teal) : QColor(LetItEditColors::deep));
        painter->drawRoundedRect(box, 4, 4);
        if (on) {
            QPainterPath tick;
            tick.moveTo(box.left() + side * 0.24, box.top() + side * 0.52);
            tick.lineTo(box.left() + side * 0.43, box.top() + side * 0.70);
            tick.lineTo(box.left() + side * 0.76, box.top() + side * 0.30);
            painter->setPen(QPen(QColor(LetItEditColors::cream), 2.2, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
            painter->setBrush(Qt::NoBrush);
            painter->drawPath(tick);
        }
        painter->restore();
    }
    QSize sizeHint(const QStyleOptionViewItem &option, const QModelIndex &index) const override
    {
        return QStyledItemDelegate::sizeHint(option, index).expandedTo(QSize(44, 24));
    }
};
} // namespace

QWidget *NewVideoDialog::contentPage()
{
    QVBoxLayout *column = nullptr;
    auto w = page(tr("What goes in it?"), tr("Use your own clips and photos, or let the AI make everything."), &column);
    auto routes = new QHBoxLayout;
    routes->setSpacing(12);
    m_routes = new QButtonGroup(this);
    m_useFootageButton = new ChoiceCard(tr("Use my footage"), tr("Pick a folder, or clips and photos. They stay where they are and are never copied or changed."), w);
    m_useFootageButton->setObjectName(QStringLiteral("newVideoUseFootage"));
    m_useFootageButton->setMinimumHeight(58);
    m_noFootageButton = new ChoiceCard(tr("100% AI"), tr("No footage needed. You choose a Look next, then say what it's about."), w);
    m_noFootageButton->setObjectName(QStringLiteral("newVideoNoFootage"));
    m_noFootageButton->setMinimumHeight(58);
    m_routes->addButton(m_useFootageButton);
    m_routes->addButton(m_noFootageButton);
    m_useFootageButton->setChecked(true);
    routes->addWidget(m_useFootageButton, 1);
    routes->addWidget(m_noFootageButton, 1);
    column->addLayout(routes);
    m_footageStack = new QStackedWidget(w);
    m_footageStack->addWidget(footageBrowser(w));
    // with no footage there is nothing to browse: what happens instead
    auto idea = new QWidget(w);
    idea->setObjectName(QStringLiteral("newVideoIdeaPanel"));
    auto ideaColumn = new QVBoxLayout(idea);
    ideaColumn->setContentsMargins(0, 8, 0, 0);
    ideaColumn->setSpacing(6);
    auto ideaTitle = new QLabel(tr("Your AI makes the whole video"), idea);
    ideaTitle->setObjectName(QStringLiteral("newVideoFieldTitle"));
    ideaColumn->addWidget(ideaTitle);
    auto ideaText = new QLabel(tr("You pick a Look and an optional Theme next. At the end you say what it's about, and you can add "
                                  "characters, a logo, photos or a script for it to use."),
                               idea);
    ideaText->setObjectName(QStringLiteral("newVideoLead"));
    ideaText->setWordWrap(true);
    ideaColumn->addWidget(ideaText);
    ideaColumn->addStretch(1);
    m_footageStack->addWidget(idea);
    column->addWidget(m_footageStack, 1);
    auto privacy = new QLabel(ConnectAi::privacyLine(), w);
    privacy->setObjectName(QStringLiteral("newVideoPrivacy"));
    privacy->setWordWrap(true);
    privacy->setProperty("studioMuted", true);
    column->addWidget(privacy);

    connect(m_noFootageButton, &QPushButton::toggled, this, [this](bool on) {
        m_noFootage = on;
        m_problem->hide();
        m_footageStack->setCurrentIndex(on ? 1 : 0);
        if (m_modern && !m_restoringRoute) {
            // another list of Styles: nothing chosen from the other one carries over
            m_browseStyle.clear();
            m_style = QStringLiteral("none");
            m_look = QStringLiteral("auto");
            m_theme = QStringLiteral("freestyle");
            m_themeChosen = false;
            m_styleExplicit = false;
            m_tab = QStringLiteral("all");
            m_tabChosen = false;
        }
        if (on) {
            m_found->setText(tr("No footage: your AI draws everything."));
            updateShapeNote();
        } else {
            countMedia();
        }
        if (m_useOneNow)
            m_useOneNow->setVisible(!on);
    });
    return w;
}

QList<NewVideoDialog::Place> NewVideoDialog::places() const
{
    QList<Place> list;
    const QString system = QDir::rootPath();
    for (const QStorageInfo &volume : QStorageInfo::mountedVolumes()) {
        if (!volume.isValid() || !volume.isReady())
            continue;
        const QString root = QDir::toNativeSeparators(volume.rootPath());
        const QString letter = root.left(2);
        QString name = volume.name().trimmed();
        if (volume.rootPath().compare(system, Qt::CaseInsensitive) == 0 || volume.rootPath().startsWith(QLatin1String("C:"), Qt::CaseInsensitive))
            name = tr("This PC");
        else if (name.isEmpty())
            name = tr("Drive");
        list.append({QStringLiteral("%1 (%2)").arg(name, letter), volume.rootPath(), letter.left(1).toUpper()});
    }
    const QString oneDrive = qEnvironmentVariable("OneDrive");
    if (!oneDrive.isEmpty() && QFileInfo(oneDrive).isDir())
        list.append({tr("OneDrive"), oneDrive, QStringLiteral("OneDrive")});
    return list;
}

// Use my footage: drive buttons, Up, the current path, the folders in it and its clips and photos. Their paths are only
// named to the AI; nothing is copied.
QWidget *NewVideoDialog::footageBrowser(QWidget *parent)
{
    auto w = new QWidget(parent);
    auto column = new QVBoxLayout(w);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(6);
    auto drives = new QHBoxLayout;
    drives->setSpacing(6);
    m_drives = new QButtonGroup(this);
    for (const Place &place : places()) {
        auto button = new QPushButton(place.label, w);
        button->setObjectName(QStringLiteral("newVideoDrive_%1").arg(place.id));
        button->setProperty("newVideoFilter", true);
        button->setCheckable(true);
        button->setAutoDefault(false);
        button->setToolTip(QDir::toNativeSeparators(place.path));
        m_drives->addButton(button);
        connect(button, &QPushButton::clicked, this, [this, path = place.path]() { m_folder->setText(QDir::toNativeSeparators(path)); });
        drives->addWidget(button);
    }
    auto up = new QPushButton(tr("Up"), w);
    up->setObjectName(QStringLiteral("newVideoUpFolder"));
    up->setAutoDefault(false);
    up->setToolTip(tr("The folder this one is in"));
    connect(up, &QPushButton::clicked, this, [this]() {
        QDir dir(m_folder->text().trimmed());
        if (dir.cdUp())
            m_folder->setText(QDir::toNativeSeparators(dir.absolutePath()));
    });
    drives->addWidget(up);
    drives->addStretch(1);
    column->addLayout(drives);
    m_folder = new QLineEdit(Settings.openPath(), w);
    m_folder->setObjectName(QStringLiteral("firstCutFolder"));
    m_folder->setAccessibleName(tr("Footage folder"));
    m_folder->setPlaceholderText(tr("The folder with your clips"));
    m_scanTimer = new QTimer(this);
    m_scanTimer->setSingleShot(true);
    m_scanTimer->setInterval(300);
    connect(m_scanTimer, &QTimer::timeout, this, [this]() { scanMedia(); });
    connect(m_folder, &QLineEdit::textChanged, this, [this]() {
        if (m_noFootage && !m_folder->text().trimmed().isEmpty())
            m_useFootageButton->setChecked(true); // typing or picking a folder means there is footage
        m_selectedFiles.clear();
        if (m_useOneNow)
            m_useOneNow->setEnabled(false);
        markDrive();
        m_scanTimer->start();
    });
    column->addWidget(m_folder);
    if (m_shortEntry) {
        m_useOneNow = new QPushButton(tr("Put one selected clip on the timeline now"), w);
        m_useOneNow->setObjectName(QStringLiteral("newVideoUseOneNow"));
        m_useOneNow->setToolTip(tr("Skip the AI: put this one video or picture on the timeline as a vertical Short you can edit yourself"));
        m_useOneNow->setEnabled(false);
        m_useOneNow->setAutoDefault(false);
        connect(m_useOneNow, &QPushButton::clicked, this, [this]() {
            if (m_selectedFiles.size() != 1)
                return;
            m_window->makeShort(m_selectedFiles);
            QDialog::accept();
        });
        column->addWidget(m_useOneNow, 0, Qt::AlignLeft);
    }
    auto browser = new QHBoxLayout;
    m_folders = new QListWidget(w);
    m_folders->setObjectName(QStringLiteral("newVideoFolders"));
    m_folders->setMinimumWidth(180);
    m_folders->setToolTip(tr("Double-click a folder to open it"));
    connect(m_folders, &QListWidget::itemActivated, this, [this](QListWidgetItem *item) {
        const QString path = item->data(Qt::UserRole).toString();
        if (QFileInfo(path).isDir())
            m_folder->setText(QDir::toNativeSeparators(path));
    });
    browser->addWidget(m_folders, 1);
    m_media = new QTreeWidget(w);
    m_media->setObjectName(QStringLiteral("newVideoMedia"));
    m_media->setIconSize(QSize(48, 32));
    m_media->setHeaderLabels({tr("Clips and photos in this folder"), tr("Length"), tr("Use")});
    m_media->header()->setStretchLastSection(false);
    m_media->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_media->header()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    m_media->header()->setSectionResizeMode(2, QHeaderView::Fixed);
    m_media->header()->resizeSection(2, 52);
    m_media->headerItem()->setTextAlignment(2, Qt::AlignCenter);
    m_media->setItemDelegateForColumn(2, new ChosenBoxDelegate(m_media));
    // a click on a file (or its box) ticks it or unticks it; nothing else changes (T176)
    m_media->setSelectionMode(QAbstractItemView::MultiSelection);
    m_media->setToolTip(tr("Click a file to tick it, click again to untick it. With nothing ticked, your AI uses the whole folder."));
    m_media->setMinimumWidth(260);
    connect(m_media, &QTreeWidget::itemSelectionChanged, this, [this]() {
        m_selectedFiles.clear();
        for (int i = 0; i < m_media->topLevelItemCount(); ++i) {
            auto row = m_media->topLevelItem(i);
            const bool on = row->isSelected();
            // the same state for screen readers and tests: the box's check state follows the highlight
            if (row->data(2, Qt::CheckStateRole).toInt() != int(on ? Qt::Checked : Qt::Unchecked))
                row->setData(2, Qt::CheckStateRole, on ? Qt::Checked : Qt::Unchecked);
            if (on)
                m_selectedFiles << row->data(0, Qt::UserRole).toString();
        }
        countMedia();
    });
    browser->addWidget(m_media, 2);
    column->addLayout(browser, 1);
    m_found = new QLabel(w);
    m_found->setObjectName(QStringLiteral("newVideoFound"));
    m_found->setProperty("studioMuted", true);
    column->addWidget(m_found);
    m_shapeNote = new QLabel(w);
    m_shapeNote->setObjectName(QStringLiteral("newVideoShapeNote"));
    m_shapeNote->setWordWrap(true);
    m_shapeNote->hide();
    column->addWidget(m_shapeNote);
    return w;
}

// the drive button of the folder shown is pressed
void NewVideoDialog::markDrive()
{
    if (!m_drives)
        return;
    const QString path = QDir::toNativeSeparators(m_folder->text().trimmed());
    QAbstractButton *best = nullptr;
    int bestLength = -1;
    for (auto button : m_drives->buttons()) {
        const QString root = QDir::toNativeSeparators(button->toolTip());
        if (path.startsWith(root, Qt::CaseInsensitive) && root.length() > bestLength) {
            best = button;
            bestLength = root.length();
        }
    }
    QSignalBlocker blocker(m_drives);
    m_drives->setExclusive(false);
    for (auto button : m_drives->buttons())
        button->setChecked(button == best);
}

// the folders inside the one shown
void NewVideoDialog::fillFolders(const QString &path)
{
    m_folders->clear();
    const auto subfolders = QDir(path).entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot | QDir::Readable, QDir::Name | QDir::IgnoreCase);
    for (const auto &folder : subfolders) {
        if (folder.fileName().startsWith(QLatin1Char('.')) || folder.fileName().startsWith(QLatin1Char('$')))
            continue;
        auto item = new QListWidgetItem(style()->standardIcon(QStyle::SP_DirIcon), folder.fileName(), m_folders);
        item->setData(Qt::UserRole, folder.absoluteFilePath());
    }
    m_folders->setVisible(m_folders->count() > 0);
}

// a YouTube video is wide: vertical clips (a phone held upright) fill only the middle of it, and they're never cropped
// into the face or shrunk to fill it, so the person hears it here, before the AI starts
void NewVideoDialog::updateShapeNote()
{
    if (!m_shapeNote || !m_media)
        return;
    int vertical = 0, wide = 0;
    for (int i = 0; i < m_media->topLevelItemCount(); ++i) {
        const auto row = m_media->topLevelItem(i);
        if (!m_selectedFiles.isEmpty() && !m_selectedFiles.contains(row->data(0, Qt::UserRole).toString()))
            continue;
        const QString shape = row->data(0, Qt::UserRole + 1).toString();
        if (shape == QLatin1String("vertical"))
            ++vertical;
        else if (shape == QLatin1String("wide"))
            ++wide;
    }
    const bool show = !m_noFootage && m_kind == QLatin1String("long") && vertical > 0 && vertical >= wide;
    if (show)
        m_shapeNote->setText(
            (wide == 0 ? tr("These clips are vertical (filmed with the phone upright).")
                       : tr("Most of these clips are vertical (filmed with the phone upright)."))
            + QLatin1Char(' ')
            + tr("A YouTube video is wide, so they'd fill only the middle third of the screen, with plain bars at the sides: "
                 "cropping them to fill it would cut off your head. They make a better Short: press Back and choose Short."));
    m_shapeNote->setVisible(show);
}

void NewVideoDialog::countMedia()
{
    updateShapeNote();
    // the count is plain to see: teal and bold while files are ticked (T176)
    const bool chosen = !m_selectedFiles.isEmpty();
    if (m_found->property("newVideoChosen").toBool() != chosen) {
        m_found->setProperty("newVideoChosen", chosen);
        m_found->setProperty("studioMuted", !chosen);
        m_found->setStyleSheet(chosen ? QStringLiteral("color: %1; font-weight: 700;").arg(QString::fromLatin1(LetItEditColors::tealLight))
                                      : QString());
    }
    if (chosen) {
        const int shown = m_media->topLevelItemCount();
        const QString of = shown > m_selectedFiles.size() ? tr(" (of %1)").arg(shown) : QString();
        m_found->setText(m_shortEntry && m_selectedFiles.size() == 1
                             ? tr("One clip selected%1. Put it on the timeline now, or press Next for an AI edit.").arg(of)
                             : m_selectedFiles.size() == 1 ? tr("1 file selected%1. Your AI will use only this one.").arg(of)
                                                           : tr("%1 files selected%2. Your AI will use only these.").arg(m_selectedFiles.size()).arg(of));
        if (m_useOneNow) {
            const QString suffix = QFileInfo(m_selectedFiles.first()).suffix().toLower();
            static const QStringList visual{"mp4", "mov", "m4v", "mkv", "avi", "mts", "webm", "mxf",
                                            "jpg", "jpeg", "png", "heic", "webp", "bmp"};
            m_useOneNow->setEnabled(m_selectedFiles.size() == 1 && visual.contains(suffix));
        }
        return;
    }
    if (m_useOneNow)
        m_useOneNow->setEnabled(false);
    const QString path = m_folder->text().trimmed();
    if (path.isEmpty() || !QFileInfo(path).isDir()) {
        m_found->setText(path.isEmpty() ? QString() : tr("No folder with that name."));
        return;
    }
    const int shown = m_media->topLevelItemCount();
    m_found->setText(shown == 1
                         ? tr("1 media file shown. Your AI uses it.")
                         : tr("%1 media files shown. None ticked: your AI uses the whole folder. Tick files to use only those.")
                               .arg(shown));
}

void NewVideoDialog::scanMedia()
{
    if (m_scan) {
        m_scan->kill();
        m_scan->deleteLater();
        m_scan = nullptr;
    }
    m_media->clear();
    const QString path = m_folder->text().trimmed();
    if (!QFileInfo(path).isDir()) {
        countMedia();
        return;
    }
    fillFolders(path);
    markDrive();
    m_found->setText(tr("Looking for media..."));
    m_scan = new QProcess(this);
    QProcess *scan = m_scan;
    connect(scan, &QProcess::readyReadStandardOutput, this, [this, scan]() {
        m_scanBuffer += scan->readAllStandardOutput();
        int newline;
        while ((newline = m_scanBuffer.indexOf('\n')) >= 0) {
            const QJsonObject item = QJsonDocument::fromJson(m_scanBuffer.left(newline)).object();
            m_scanBuffer.remove(0, newline + 1);
            if (item.contains("file")) {
                const QJsonObject file = item.value("file").toObject();
                QString length;
                if (file.contains("duration_s")) {
                    const int seconds = qRound(file.value("duration_s").toDouble());
                    length = QStringLiteral("%1:%2").arg(seconds / 60).arg(seconds % 60, 2, 10, QLatin1Char('0'));
                }
                auto row = new QTreeWidgetItem(m_media, {file.value("name").toString(), length});
                // the box is drawn from the highlight; it is never ticked on its own (that would let them disagree)
                row->setFlags(row->flags() & ~Qt::ItemIsUserCheckable);
                row->setData(2, Qt::CheckStateRole, Qt::Unchecked);
                row->setData(2, Qt::AccessibleTextRole, tr("Use %1").arg(file.value("name").toString()));
                row->setData(0, Qt::UserRole, file.value("path").toString());
                row->setToolTip(0, file.value("kind").toString());
                row->setData(0, Qt::UserRole + 1, file.value("orientation").toString());
                countMedia();
            } else if (item.contains("thumbnail")) {
                const QJsonObject thumb = item.value("thumbnail").toObject();
                const QString path = thumb.value("path").toString();
                const QIcon icon(thumb.value("image").toString());
                for (int i = 0; i < m_media->topLevelItemCount(); ++i) {
                    auto row = m_media->topLevelItem(i);
                    if (row->data(0, Qt::UserRole).toString() == path) {
                        row->setIcon(0, icon);
                        break;
                    }
                }
            } else if (item.contains("error")) {
                m_found->setText(item.value("error").toString());
            }
        }
    });
    connect(scan, &QProcess::finished, this, [this, scan]() {
        if (m_scan == scan) {
            m_scan = nullptr;
            countMedia();
        }
        scan->deleteLater();
    });
    m_scanBuffer.clear();
    const QString cache = leSettings().fileName() + QStringLiteral(".media-cache.json");
    scan->start(aiChatSettings().value("python").toString(),
        {aiRootPath(QStringLiteral("bridge/new_video_media.py")), path,
         aiRootPath(QStringLiteral("app/ffprobe.exe")), cache});
}

} // namespace NewVideo
