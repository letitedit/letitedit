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

#include "letitedit/panels/imagegen.h"

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/chat/connectai.h"
#include "docks/timelinedock.h"
#include "letitedit/dialogs/letools.h"
#include "mainwindow.h"
#include "mltcontroller.h"

#include <QCheckBox>
#include <QDateTime>
#include <QDialog>
#include <QDir>
#include <QDockWidget>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFrame>
#include <QHBoxLayout>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QListWidget>
#include <QPixmap>
#include <QPlainTextEdit>
#include <QPointer>
#include <QPushButton>
#include <QRadioButton>
#include <QSpinBox>
#include <QTimer>
#include <QVBoxLayout>

namespace ImageGenerator {

namespace {

constexpr int kThumb = 150;

class ImageGeneratorDialog : public QDialog
{
public:
    explicit ImageGeneratorDialog(MainWindow *window)
        : QDialog(window)
        , m_window(window)
        , m_status(new LeToolRun(this))
    {
        setObjectName(QStringLiteral("imageGeneratorDialog"));
        setWindowTitle(tr("Image generator"));
        setMinimumSize(860, 560);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        auto heading = new QLabel(tr("Make a picture for this video"), this);
        heading->setProperty("studioHeading", true);
        column->addWidget(heading);
        m_who = new QLabel(this);
        m_who->setObjectName(QStringLiteral("imageGenWho"));
        m_who->setWordWrap(true);
        m_who->setProperty("studioMuted", true);
        column->addWidget(m_who);

        m_switch = new QCheckBox(this);
        m_switch->setObjectName(QStringLiteral("imageGenOtherAi"));
        m_switch->hide();
        column->addWidget(m_switch);
        connect(m_switch, &QCheckBox::clicked, this, [this](bool on) { switched(on); });

        buildAiNotice(column);
        auto middle = new QHBoxLayout;
        middle->setSpacing(16);
        column->addLayout(middle, 1);

        buildImageRequest(middle);
        buildImageHistory(middle);
        m_line = new QLabel(this);
        m_line->setObjectName(QStringLiteral("imageGenStatus"));
        m_line->setWordWrap(true);
        column->addWidget(m_line);

        m_status->done = [this](bool ok, const QJsonObject &result, const QString &why) { showWho(ok, result, why); };
        auto timer = new QTimer(this);
        timer->setInterval(3000);
        connect(timer, &QTimer::timeout, this, [this]() { refreshHistory(); });
        timer->start();
        refreshWho();
        refreshHistory();
        selectionChanged();
    }

    void refreshWho()
    {
        m_who->setText(tr("Looking at what can draw on this PC…"));
        m_status->start(QStringLiteral("image-status"), {});
    }

    void refreshHistory()
    {
        const QString folder = sideFolder();
        QStringList stamp;
        const QFileInfoList cars = folder.isEmpty() ? QFileInfoList()
                                                    : QDir(folder).entryInfoList({QStringLiteral("generated-image-*.json")}, QDir::Files, QDir::Name);
        for (const auto &car : cars)
            stamp << car.fileName() + QString::number(car.lastModified().toMSecsSinceEpoch());
        showDrawing(folder);
        if (stamp == m_stamp)
            return;
        m_stamp = stamp;
        const QString keep = selectedPath();
        m_history->clear();
        for (const auto &car : cars) {
            QFile f(car.absoluteFilePath());
            if (!f.open(QIODevice::ReadOnly))
                continue;
            const QJsonObject row = QJsonDocument::fromJson(f.readAll()).object();
            const QString path = row.value(QStringLiteral("path")).toString();
            if (!QFileInfo::exists(path))
                continue;
            auto item = new QListWidgetItem(QIcon(QPixmap(path).scaled(kThumb, kThumb, Qt::KeepAspectRatio, Qt::SmoothTransformation)),
                                            row.value(QStringLiteral("character")).toString(), m_history);
            item->setData(Qt::UserRole, path);
            item->setData(Qt::UserRole + 1, row.value(QStringLiteral("fit_path")).toString());
            const QString by = row.value(QStringLiteral("made_by")).toObject().value(QStringLiteral("program")).toString();
            const QJsonArray size = row.value(QStringLiteral("size")).toArray();
            item->setData(Qt::UserRole + 2, tr("%1  (%2 x %3, drawn by %4, AI-made)")
                                                 .arg(row.value(QStringLiteral("prompt")).toString())
                                                 .arg(size.at(0).toInt())
                                                 .arg(size.at(1).toInt())
                                                 .arg(by.isEmpty() ? tr("an AI") : by));
            item->setToolTip(item->data(Qt::UserRole + 2).toString());
            if (path == keep)
                m_history->setCurrentItem(item);
        }
        if (m_history->count() && !m_history->currentItem())
            m_history->setCurrentRow(m_history->count() - 1);
        m_empty->setVisible(!m_history->count());
        selectionChanged();
    }

private:
    void buildAiNotice(QVBoxLayout *column)
    {
        m_notice = new QFrame(this);
        m_notice->setObjectName(QStringLiteral("imageGenNotice"));
        m_notice->setFrameShape(QFrame::StyledPanel);
        auto noticeColumn = new QVBoxLayout(m_notice);
        m_noticeText = new QLabel(m_notice);
        m_noticeText->setObjectName(QStringLiteral("imageGenNoticeText"));
        m_noticeText->setWordWrap(true);
        noticeColumn->addWidget(m_noticeText);
        auto noticeRow = new QHBoxLayout;
        auto turnOn = new QPushButton(tr("Turn it on"), m_notice);
        turnOn->setObjectName(QStringLiteral("imageGenTurnOn"));
        auto notNow = new QPushButton(tr("Not now"), m_notice);
        notNow->setObjectName(QStringLiteral("imageGenNotNow"));
        noticeRow->addStretch();
        noticeRow->addWidget(notNow);
        noticeRow->addWidget(turnOn);
        noticeColumn->addLayout(noticeRow);
        m_notice->hide();
        column->addWidget(m_notice);
        connect(turnOn, &QPushButton::clicked, this, [this]() {
            aiChatSaveSettings(QJsonObject{{QStringLiteral("image_other_ai"), true},
                                           {QStringLiteral("image_other_ai_notice_seen"), true}});
            m_notice->hide();
            refreshWho();
        });
        connect(notNow, &QPushButton::clicked, this, [this]() {
            m_notice->hide();
            m_switch->setChecked(false);
        });
    }

    void buildImageRequest(QHBoxLayout *middle)
    {
        // Left: what to make
        auto left = new QVBoxLayout;
        left->setSpacing(6);
        middle->addLayout(left, 1);
        left->addWidget(new QLabel(tr("What should the picture show?"), this));
        m_prompt = new QPlainTextEdit(this);
        m_prompt->setObjectName(QStringLiteral("imageGenPrompt"));
        m_prompt->setPlaceholderText(tr("For example: an empty mountain valley at dusk, flat colors, a blank wooden sign in front"));
        left->addWidget(m_prompt, 1);
        m_editing = new QLabel(this);
        m_editing->setObjectName(QStringLiteral("imageGenEditing"));
        m_editing->setWordWrap(true);
        m_editing->hide();
        left->addWidget(m_editing);
        m_stopEditing = new QPushButton(tr("Make a new picture instead"), this);
        m_stopEditing->setObjectName(QStringLiteral("imageGenStopEditing"));
        m_stopEditing->hide();
        left->addWidget(m_stopEditing);
        connect(m_stopEditing, &QPushButton::clicked, this, [this]() { setEditing(QString()); });

        left->addWidget(new QLabel(tr("Pictures to follow (a character, a place, a style), up to 5"), this));
        m_references = new QListWidget(this);
        m_references->setObjectName(QStringLiteral("imageGenReferences"));
        m_references->setMaximumHeight(84);
        left->addWidget(m_references);
        auto referenceRow = new QHBoxLayout;
        auto add = new QPushButton(tr("Add a picture..."), this);
        add->setObjectName(QStringLiteral("imageGenAddReference"));
        auto remove = new QPushButton(tr("Remove"), this);
        remove->setObjectName(QStringLiteral("imageGenRemoveReference"));
        referenceRow->addWidget(add);
        referenceRow->addWidget(remove);
        referenceRow->addStretch();
        left->addLayout(referenceRow);
        connect(add, &QPushButton::clicked, this, [this]() {
            for (const QString &file : QFileDialog::getOpenFileNames(this, tr("Pictures to follow"), QString(),
                                                                     tr("Pictures (*.png *.jpg *.jpeg *.webp)")))
                addReference(file);
        });
        connect(remove, &QPushButton::clicked, this, [this]() { delete m_references->currentItem(); });

        auto options = new QHBoxLayout;
        options->addWidget(new QLabel(tr("How many"), this));
        m_count = new QSpinBox(this);
        m_count->setObjectName(QStringLiteral("imageGenCount"));
        m_count->setRange(1, 6);
        options->addWidget(m_count);
        options->addSpacing(16);
        m_wide = new QRadioButton(tr("Wide"), this);
        m_wide->setObjectName(QStringLiteral("imageGenWide"));
        m_tall = new QRadioButton(tr("Tall"), this);
        m_tall->setObjectName(QStringLiteral("imageGenTall"));
        const bool tall = MLT.profile().height() > MLT.profile().width();
        (tall ? m_tall : m_wide)->setChecked(true);
        options->addWidget(m_wide);
        options->addWidget(m_tall);
        options->addStretch();
        m_make = new QPushButton(tr("Make"), this);
        m_make->setObjectName(QStringLiteral("imageGenMake"));
        m_make->setDefault(true);
        m_make->setProperty("studioPrimary", true);
        options->addWidget(m_make);
        left->addLayout(options);
        connect(m_make, &QPushButton::clicked, this, [this]() { make(); });
    }

    void buildImageHistory(QHBoxLayout *middle)
    {
        // Right: what was made
        auto right = new QVBoxLayout;
        right->setSpacing(6);
        middle->addLayout(right, 1);
        right->addWidget(new QLabel(tr("Made for this video"), this));
        m_drawing = new QLabel(this);
        m_drawing->setObjectName(QStringLiteral("imageGenDrawing"));
        m_drawing->setWordWrap(true);
        m_drawing->hide();
        right->addWidget(m_drawing);
        m_history = new QListWidget(this);
        m_history->setObjectName(QStringLiteral("imageGenHistory"));
        m_history->setViewMode(QListView::IconMode);
        m_history->setResizeMode(QListView::Adjust);
        m_history->setMovement(QListView::Static);
        m_history->setIconSize(QSize(kThumb, kThumb));
        m_history->setSpacing(6);
        right->addWidget(m_history, 1);
        m_empty = new QLabel(tr("Nothing yet. Pictures your AI makes for this video show up here, with the words that made them."), this);
        m_empty->setObjectName(QStringLiteral("imageGenEmpty"));
        m_empty->setWordWrap(true);
        m_empty->setProperty("studioMuted", true);
        right->addWidget(m_empty);
        m_words = new QLabel(this);
        m_words->setObjectName(QStringLiteral("imageGenWords"));
        m_words->setWordWrap(true);
        m_words->setTextInteractionFlags(Qt::TextSelectableByMouse);
        right->addWidget(m_words);
        auto actions = new QHBoxLayout;
        m_place = new QPushButton(tr("Put on the timeline"), this);
        m_place->setObjectName(QStringLiteral("imageGenPlace"));
        m_edit = new QPushButton(tr("Edit this image"), this);
        m_edit->setObjectName(QStringLiteral("imageGenEdit"));
        m_follow = new QPushButton(tr("Follow this one"), this);
        m_follow->setObjectName(QStringLiteral("imageGenFollow"));
        actions->addWidget(m_place);
        actions->addWidget(m_edit);
        actions->addWidget(m_follow);
        actions->addStretch();
        right->addLayout(actions);
        connect(m_place, &QPushButton::clicked, this, [this]() { place(); });
        connect(m_edit, &QPushButton::clicked, this, [this]() {
            const QString path = selectedPath();
            if (!path.isEmpty())
                setEditing(path);
        });
        connect(m_follow, &QPushButton::clicked, this, [this]() {
            const QString path = selectedPath();
            if (!path.isEmpty())
                addReference(path);
        });
        connect(m_history, &QListWidget::currentRowChanged, this, [this]() { selectionChanged(); });
    }

    QString projectFile() const { return m_window->fileName(); }

    // <video>.letitedit/images, as bridge/image_gen.py keeps it
    QString sideFolder() const
    {
        const QString project = projectFile();
        if (project.isEmpty())
            return QString();
        const QFileInfo info(project);
        return info.dir().filePath(info.completeBaseName() + QStringLiteral(".letitedit/images"));
    }

    QString selectedPath() const
    {
        auto item = m_history->currentItem();
        return item ? item->data(Qt::UserRole).toString() : QString();
    }

    void selectionChanged()
    {
        const bool any = m_history->currentItem() != nullptr;
        m_place->setEnabled(any);
        m_edit->setEnabled(any);
        m_follow->setEnabled(any);
        m_words->setText(any ? m_history->currentItem()->data(Qt::UserRole + 2).toString() : QString());
    }

    // The visible row while a program is drawing for this video: the newest line of its log.
    void showDrawing(const QString &folder)
    {
        QFile log(QDir(folder).filePath(QStringLiteral("log.jsonl")));
        QString line;
        if (!folder.isEmpty() && log.open(QIODevice::ReadOnly)) {
            const QList<QByteArray> rows = log.readAll().split('\n');
            for (int i = rows.size() - 1; i >= 0 && line.isEmpty(); --i) {
                if (rows[i].trimmed().isEmpty())
                    continue;
                const QJsonObject row = QJsonDocument::fromJson(rows[i]).object();
                if (row.value(QStringLiteral("state")).toString() == QLatin1String("drawing")) {
                    const QString by = ConnectAi::programName(row.value(QStringLiteral("by")).toString());
                    line = tr("%1 is drawing: %2").arg(by.isEmpty() ? tr("Your key's maker") : by, row.value(QStringLiteral("prompt")).toString().left(120));
                }
                break;
            }
        }
        m_drawing->setText(line);
        m_drawing->setVisible(!line.isEmpty());
    }

    void showWho(bool ok, const QJsonObject &status, const QString &why)
    {
        if (!ok) {
            m_who->setText(why.isEmpty() ? tr("letitedit could not check what can draw on this PC.") : why);
            return;
        }
        QString name;
        // T234: the first one found, as the tools list them best first (when on, the one that draws)
        const auto look = [&name](const QJsonArray &rows) {
            for (const auto &row : rows) {
                if (name.isEmpty() && row.toObject().value(QStringLiteral("route")).toString() == QLatin1String("other"))
                    name = ConnectAi::programName(row.toObject().value(QStringLiteral("by")).toString());
            }
        };
        look(status.value(QStringLiteral("routes")).toArray());
        look(status.value(QStringLiteral("off")).toArray());
        m_otherName = name;
        const bool on = status.value(QStringLiteral("other_ai_on")).toBool();
        m_switch->setVisible(!name.isEmpty() || on);
        m_switch->setChecked(on);
        m_switch->setText(tr("Let %1 draw for the AI you're using").arg(name.isEmpty() ? tr("another AI on this PC") : name));
        const QJsonObject now = status.value(QStringLiteral("draws_now")).toObject();
        const QString route = now.value(QStringLiteral("route")).toString();
        const QString drawer = now.value(QStringLiteral("name")).toString();
        if (route == QLatin1String("own"))
            m_who->setText(tr("%1 draws these itself, on your own plan.").arg(drawer));
        else if (route == QLatin1String("key"))
            m_who->setText(tr("%1 draws these through your own pay-per-picture account (set up with a key), so each picture costs you a little.").arg(drawer));
        else if (route == QLatin1String("other"))
            m_who->setText(tr("%1 draws these and hands them to the AI you're using. It runs on your own plan.").arg(drawer));
        else
            m_who->setText(tr("Nothing on this PC can draw a picture for the AI you're using right now. You can still ask: your AI "
                              "will say so, and it can build a simpler picture itself instead."));
    }

    void switched(bool on)
    {
        if (!on) {
            m_notice->hide();
            aiChatSaveSettings(QJsonObject{{QStringLiteral("image_other_ai"), false}});
            refreshWho();
            return;
        }
        if (aiChatRawSettings().value(QStringLiteral("image_other_ai_notice_seen")).toBool()) {
            aiChatSaveSettings(QJsonObject{{QStringLiteral("image_other_ai"), true}});
            refreshWho();
            return;
        }
        // The owner's words (3 Nov): general, so they cover every subscription.
        m_noticeText->setText(tr("When your AI needs a picture, letitedit can ask your other AI subscription to draw it, on your own plan. The picture goes back to your AI so it can keep editing. You'll see each one here, marked as AI-made. The company behind that AI hasn't said whether it allows this, and if it says no, letitedit turns this off. You can turn it off here at any time, and your AI then draws in code."));
        m_notice->show();
    }

    void addReference(const QString &file)
    {
        if (m_references->count() >= 5) {
            m_line->setText(tr("Up to 5 pictures can be followed. Remove one first."));
            return;
        }
        const QString path = QDir::toNativeSeparators(file);
        if (m_references->findItems(path, Qt::MatchExactly).isEmpty())
            m_references->addItem(path);
    }

    void setEditing(const QString &path)
    {
        m_editPath = path;
        m_editing->setText(path.isEmpty() ? QString() : tr("Editing %1. Say what should change; the rest stays the same.").arg(QFileInfo(path).fileName()));
        m_editing->setVisible(!path.isEmpty());
        m_stopEditing->setVisible(!path.isEmpty());
        m_make->setText(path.isEmpty() ? tr("Make") : tr("Change it"));
    }

    bool ask(const QString &text, const QString &summary, const QString &line)
    {
        if (!aiChatRequest(m_window, text, summary)) {
            const QString refusal = aiChatRefusal();
            m_line->setText(refusal.isEmpty() ? tr("Your AI is still busy with the last request. Try again when it has answered (or "
                                                   "press Stop in the chat).")
                                              : refusal);
            return false;
        }
        if (auto chat = m_window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
            chat->show();
            chat->raise();
        }
        m_line->setText(line);
        return true;
    }

    void make()
    {
        const QString words = m_prompt->toPlainText().trimmed();
        if (projectFile().isEmpty()) {
            m_line->setText(tr("Open or save your video first: pictures are kept beside it."));
            return;
        }
        if (words.isEmpty()) {
            m_line->setText(tr("Say what the picture should show first."));
            return;
        }
        QJsonObject call{{QStringLiteral("project"), QDir::toNativeSeparators(projectFile())},
                         {QStringLiteral("prompt"), words},
                         {QStringLiteral("count"), m_count->value()},
                         {QStringLiteral("shape"), m_tall->isChecked() ? QStringLiteral("tall") : QStringLiteral("wide")}};
        QJsonArray references;
        for (int i = 0; i < m_references->count(); ++i)
            references.append(m_references->item(i)->text());
        if (!references.isEmpty())
            call.insert(QStringLiteral("references"), references);
        if (!m_editPath.isEmpty())
            call.insert(QStringLiteral("edit"), QDir::toNativeSeparators(m_editPath));
        const QString request = QStringLiteral(
                                    "From the Image generator: make this with letitedit_image, these exact arguments: %1\n"
                                    "The words are the person's, so pass them on as they are, and keep to what they asked: don't put it on the "
                                    "timeline. Say in one line who drew it. If nothing can draw it, say that in one line and offer to draw it in code.")
                                    .arg(QString::fromUtf8(QJsonDocument(call).toJson(QJsonDocument::Compact)));
        if (ask(request, tr("Image generator: %1").arg(words.left(80)), tr("Your AI is asking for the picture. It shows up here when it's done.")))
            setEditing(QString());
    }

    void place()
    {
        auto item = m_history->currentItem();
        if (!item)
            return;
        const QString fit = item->data(Qt::UserRole + 1).toString();
        const QString path = QDir::toNativeSeparators(fit.isEmpty() ? item->data(Qt::UserRole).toString() : fit);
        const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
        const int frame = MAIN.timelineDock() ? qMax(0, MAIN.timelineDock()->position()) : 0;
        const QString request = QStringLiteral(
                                    "From the Image generator: put this picture on the timeline of %1 with letitedit_timeline_apply, at the playhead "
                                    "(%2 seconds), on a video track above the picture, for 4 seconds: %3\nDon't make anything new. Say in one line where it went.")
                                    .arg(QDir::toNativeSeparators(projectFile()))
                                    .arg(frame / fps, 0, 'f', 3)
                                    .arg(path);
        ask(request, tr("Image generator: put a picture on the timeline"), tr("Your AI is putting it on the timeline."));
    }

    MainWindow *m_window;
    LeToolRun *m_status;
    QLabel *m_who, *m_noticeText, *m_editing, *m_drawing, *m_empty, *m_words, *m_line;
    QCheckBox *m_switch;
    QFrame *m_notice;
    QPlainTextEdit *m_prompt;
    QPushButton *m_stopEditing, *m_make, *m_place, *m_edit, *m_follow;
    QListWidget *m_references, *m_history;
    QSpinBox *m_count;
    QRadioButton *m_wide, *m_tall;
    QString m_editPath, m_otherName;
    QStringList m_stamp;
};

} // namespace

void show(MainWindow *window)
{
    static QPointer<ImageGeneratorDialog> dialog;
    if (!dialog) {
        dialog = new ImageGeneratorDialog(window);
        dialog->setAttribute(Qt::WA_DeleteOnClose);
    } else {
        dialog->refreshWho();
        dialog->refreshHistory();
    }
    dialog->show();
    dialog->raise();
    dialog->activateWindow();
}

} // namespace ImageGenerator
