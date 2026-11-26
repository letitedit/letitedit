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

// New video: the one browser of Looks and styles (the catalogue's older layout) and the review buttons of test profiles.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// Everything this video can use. From looks\manifest.json (through bridge\looks.py) and the style list, so adding a Look
// or a folder needs no editor build. Looks that work with no footage are for "Create from an idea", unless the manifest
// says `works_with: both`.
QList<NewVideoDialog::BrowserEntry> NewVideoDialog::browserEntries(QList<QPair<QString, QString>> *filters) const
{
    QList<BrowserEntry> entries;
    const bool idea = m_noFootage;
    const auto addFilter = [filters](const QString &id, const QString &label) {
        for (const auto &f : std::as_const(*filters))
            if (f.first == id)
                return;
        filters->append({id, label});
    };
    filters->append({QStringLiteral("all"), tr("All")});
    if (!idea) {
        BrowserEntry none;
        none.style = QStringLiteral("none");
        none.category = QStringLiteral("all");
        none.label = tr("Let the AI choose");
        none.line = tr("Your AI picks the pace, captions, effects and music. The easiest choice.");
        none.name = QStringLiteral("newVideoStyle_none");
        entries << none;
    }
    for (const auto &s : std::as_const(m_lookStyles)) {
        const bool fits = m_kind == QLatin1String("both") || m_kind == QLatin1String("custom")
                          || s.kind == QLatin1String("both") || s.kind == m_kind;
        if (!fits)
            continue;
        bool any = false;
        for (const auto &look : s.looks) {
            const bool valid = look.worksWith == QLatin1String("both")
                               || look.worksWith == (idea ? QLatin1String("no-footage") : QLatin1String("footage"));
            if (!valid)
                continue;
            any = true;
            BrowserEntry e;
            e.style = s.id;
            e.look = look.id;
            const LookFolder *folder = lookFolder(s, look.folder);
            e.category = folder ? folder->id : s.id;
            e.label = look.label;
            e.line = look.line;
            e.choice = &look;
            e.name = QStringLiteral("newVideoLook_%1").arg(look.id);
            entries << e;
            addFilter(e.category, folder ? folder->label : s.filterLabel);
        }
        // a Style that works on footage can leave the choice among its own Looks to the AI (T43)
        if (any && !idea && s.footage != QLatin1String("no")) {
            BrowserEntry pick;
            pick.style = s.id;
            pick.look = QStringLiteral("auto");
            pick.category = s.id;
            pick.onlyInCategory = true;
            pick.label = tr("Let the AI pick");
            pick.line = tr("It looks at your footage and picks the Look that suits it, then tells you which one and why.");
            pick.name = QStringLiteral("newVideoLook_auto");
            entries << pick;
        }
    }
    if (!idea) {
        // the person's own, under My settings: their styles and the detailed settings
        filters->append({QStringLiteral("mine"), tr("My Looks")});
        BrowserEntry custom;
        custom.style = QStringLiteral("custom");
        custom.category = QStringLiteral("mine");
        custom.onlyInCategory = true;
        custom.label = tr("Custom");
        custom.line = tr("Choose how much of each ingredient goes into your video. Everything starts on AI decides.");
        custom.name = QStringLiteral("newVideoStyle_custom");
        entries << custom;
    }
    return entries;
}

void NewVideoDialog::reviewEntry(const QString &kind, const QString &id, const QString &action)
{
    if (m_reviewBusy)
        return;
    m_reviewBusy = true;
    auto process = new QProcess(this);
    connect(process, &QProcess::finished, this, [this, process](int code, QProcess::ExitStatus) {
        m_reviewBusy = false;
        if (code) {
            m_problem->setText(QString::fromUtf8(process->readAllStandardError()));
            m_problem->show();
        } else {
            loadLooks();
        }
        process->deleteLater();
    });
    connect(process, &QProcess::errorOccurred, this, [this, process](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            m_reviewBusy = false;
            m_problem->setText(tr("Couldn't save that review. Nothing was changed."));
            m_problem->show();
            process->deleteLater();
        }
    });
    process->start(aiChatSettings().value("python").toString(),
                   {aiRootPath(QStringLiteral("bridge/looks.py")), QStringLiteral("--review"), kind, id, action});
}

void NewVideoDialog::addReviewButtons(QBoxLayout *row, const QString &kind, const QString &id, const QString &review, bool cut)
{
    if (!m_review)
        return;
    if (review == QLatin1String("new")) {
        auto badge = new QLabel(tr("New"), row->parentWidget());
        badge->setObjectName(QStringLiteral("newVideoNew_%1_%2").arg(kind, id));
        row->addWidget(badge);
    }
    const QStringList actions = cut ? QStringList{QStringLiteral("restore")}
                               : review == QLatin1String("new") ? QStringList{QStringLiteral("keep"), QStringLiteral("cut")}
                                                                : QStringList{QStringLiteral("cut")};
    for (const auto &action : actions) {
        auto button = new QPushButton(action == QLatin1String("keep") ? tr("Keep")
                                      : action == QLatin1String("cut") ? tr("Cut") : tr("Restore"), row->parentWidget());
        button->setAutoDefault(false);
        button->setObjectName(QStringLiteral("newVideoReview_%1_%2_%3").arg(kind, id, action));
        connect(button, &QPushButton::clicked, this, [this, kind, id, action]() { reviewEntry(kind, id, action); });
        row->addWidget(button);
    }
}

// T189: one of the person's own Looks can be renamed from its card: a small Rename under it, or a right-click on it. Only
// the name changes (learned_looks.py rename); the catalogue is read again so every card and step shows the new name.
void NewVideoDialog::addRenameButton(QBoxLayout *column, QWidget *card, const QString &id, const QString &label)
{
    const auto rename = [this, id, label]() {
        if (LearnLooks::renameLook(this, id, label))
            loadLooks();
    };
    auto button = new QPushButton(tr("Rename"), column->parentWidget());
    button->setObjectName(QStringLiteral("newVideoLookRename_%1").arg(id));
    button->setAutoDefault(false);
    button->setFlat(true);
    button->setProperty("studioMuted", true);
    button->setToolTip(tr("Give this Look a name of your own"));
    connect(button, &QPushButton::clicked, this, rename);
    column->addWidget(button, 0, Qt::AlignLeft);
    card->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(card, &QWidget::customContextMenuRequested, this, [card, rename](const QPoint &at) {
        QMenu menu(card);
        menu.addAction(tr("Rename this Look..."), rename);
        menu.exec(card->mapToGlobal(at));
    });
    card->setToolTip(tr("Yours: learned from your own video and kept on this PC. Right-click to rename it."));
}

bool NewVideoDialog::entryChosen(const BrowserEntry &e) const
{
    return e.style == m_style && (e.look.isEmpty() || e.look == m_look);
}

// The Look stage's one browser: filters, then cards. The choice is kept in m_style and m_look, so a filter that hides
// the chosen card changes nothing; a line then says what stays chosen.
void NewVideoDialog::fillBrowser()
{
    if (m_modern) {
        fillModernBrowser();
        return;
    }
    using namespace LetItEditColors;
    QList<QPair<QString, QString>> filters;
    QList<BrowserEntry> entries = browserEntries(&filters);
    const bool loading = m_catalogState == 0 || m_looksState == 0;
    // what is chosen has to be something this video can use
    if (!m_personChose && !loading && !m_noFootage)
        m_style = mineByDefault();
    const auto chosenEntry = [&]() -> const BrowserEntry * {
        for (const auto &e : std::as_const(entries))
            if (entryChosen(e))
                return &e;
        return nullptr;
    };
    if (!chosenEntry() && !loading) {
        QString was;
        if (const LookChoice *look = chosenLookCard())
            was = look->label;
        else if (const StyleChoice *c = chosenCatalogCard())
            was = c->label;
        if (m_personChose && !was.isEmpty())
            m_lookNote = m_noFootage ? tr("%1 needs footage, so it's no longer chosen.").arg(was)
                         : (chosenLookCard() && chosenLookCard()->worksWith == QLatin1String("no-footage"))
                             ? tr("%1 is only for Create from an idea, so it's no longer chosen.").arg(was)
                             : tr("%1 doesn't fit this kind of video, so it's no longer chosen.").arg(was);
        m_personChose = false;
        m_look = QStringLiteral("auto");
        m_style = QStringLiteral("none");
        if (m_noFootage) {
            // no footage: nothing for the AI to cut, so a Look has to be picked; with only one, it's that one
            m_look.clear();
            for (const auto &e : std::as_const(entries)) {
                m_style = e.style;
                break;
            }
            if (entries.size() == 1)
                m_look = entries.first().look;
        } else if (!chosenEntry()) {
            m_style = QStringLiteral("none");
        }
    }
    // the filter: where the choice is, the first time
    const auto hasFilter = [&](const QString &id) {
        for (const auto &f : std::as_const(filters))
            if (f.first == id)
                return true;
        return false;
    };
    if (m_filter.isEmpty() || !hasFilter(m_filter)) {
        m_filter = QStringLiteral("all");
        if (const BrowserEntry *e = chosenEntry())
            if (e->onlyInCategory)
                m_filter = e->category;
    }
    const QWidget *focused = focusWidget();
    const bool chipFocused = focused && focused->property("newVideoFilter").toBool();
    clearLayout(m_filterRow);
    QPushButton *current = nullptr;
    for (const auto &f : std::as_const(filters)) {
        const QString chipWords = fontMetrics().elidedText(f.second, Qt::ElideRight, 260);
        auto chip = new QPushButton(QString(chipWords).replace(QLatin1Char('&'), QStringLiteral("&&")), m_filterRow->parentWidget());
        chip->setToolTip(f.second);
        chip->setAccessibleName(f.second);
        chip->setObjectName(QStringLiteral("newVideoLookFilter_%1").arg(f.first));
        chip->setProperty("newVideoFilter", true);
        chip->setCheckable(true);
        chip->setChecked(f.first == m_filter);
        chip->setAutoDefault(false);
        chip->setCursor(Qt::PointingHandCursor);
        connect(chip, &QPushButton::clicked, this, [this, id = f.first]() {
            m_filter = id;
            m_problem->hide();
            fillBrowser();
        });
        m_filterRow->addWidget(chip);
        if (f.first == m_filter)
            current = chip;
    }
    m_filterRow->addStretch(1);
    if (chipFocused && current)
        current->setFocus();

    const auto shown = buildBrowserCards(entries);

    // a line when the choice is out of view, or was let go
    QString chosenWords = m_lookNote;
    const BrowserEntry *chosen = chosenEntry();
    bool visible = false;
    if (chosen)
        for (const BrowserEntry *e : std::as_const(shown))
            visible = visible || e == chosen;
    if (chosen && !visible)
        chosenWords += (chosenWords.isEmpty() ? QString() : QStringLiteral(" ")) + tr("Chosen now: %1.").arg(chosen->label);
    m_chosenLine->setText(chosenWords);
    m_chosenLine->setVisible(!chosenWords.isEmpty());
    m_styleNote->setText(loading ? tr("Loading your Looks...")
                         : m_catalogState < 0 && !m_noFootage ? tr("Couldn't load the Looks list, so your AI decides.")
                         : m_noFootage && entries.isEmpty() ? tr("No Look that draws a whole video from nothing is installed yet.")
                                                            : QString());
    m_styleNote->setVisible(!m_styleNote->text().isEmpty());
}

QList<const NewVideoDialog::BrowserEntry *> NewVideoDialog::buildBrowserCards(const QList<BrowserEntry> &entries)
{
    // the cards
    m_lookCards.clear();
    m_filling = true;
    const auto forget = [this](QWidget *w) {
        if (auto b = qobject_cast<QAbstractButton *>(w))
            m_styles->removeButton(b);
    };
    clearLayout(m_styleGrid, forget);
    for (int i = 0; i < m_styleGrid->rowCount(); ++i)
        m_styleGrid->setRowStretch(i, 0);
    for (int i = 0; i < m_styleGrid->columnCount(); ++i)
        m_styleGrid->setColumnStretch(i, 0);
    QList<const BrowserEntry *> shown;
    int clips = 0;
    for (const auto &e : std::as_const(entries)) {
        const bool inView = m_filter == QLatin1String("all") ? !e.onlyInCategory : e.category == m_filter;
        if (!inView)
            continue;
        shown << &e;
        if (e.choice && !e.choice->preview.isEmpty())
            ++clips;
    }
    const LookCard::Playback playback = lookPlayback(clips);
    // each preview 9:16: as tall as the window lets one row show, as wide as that makes it
    const int roomHigh = qMax(240, height() - 262);
    const int previewWidth = qBound(112, (roomHigh - 24 - 6 - 104) * 9 / 16, 190);
    const QSize pictureSize(previewWidth, previewWidth * 16 / 9);
    const int roomWide = qMax(420, width() - 48 - 22);
    const int cardWidth = pictureSize.width() + 2 * LookCard::kCardMargin;
    const int columns = qMax(1, (roomWide + 12) / (cardWidth + 12));
    int placed = 0;
    for (const BrowserEntry *e : std::as_const(shown)) {
        QPixmap placeholder;
        if (!e->choice) {
            if (e->style == QLatin1String("none") || e->look == QLatin1String("auto"))
                placeholder = aiPickPicture(pictureSize);
            else if (!e->picture.isNull())
                placeholder = framedPicture(e->picture, pictureSize);
            else
                placeholder = framedPicture(placeholderPicture(e->label, false), pictureSize);
        }
        const QString cardId = e->name.mid(e->name.indexOf(QLatin1Char('_')) + 1);
        auto card = new LookCard(cardId, e->label, e->line, e->choice ? e->choice->preview : QString(),
                                 e->choice ? e->choice->poster : QString(), placeholder, pictureSize, playback, m_styleHolder);
        card->setObjectName(e->name);
        card->setProperty("style", e->style);
        card->setProperty("look", e->look);
        if (!e->badge.isEmpty())
            card->setBadge(e->badge);
        card->onSound([this](LookCard *loud, bool on) {
            if (on)
                for (auto other : std::as_const(m_lookCards))
                    if (other && other != loud)
                        other->silence(); // one preview is heard at a time
        });
        m_styles->addButton(card);
        m_styleGrid->addWidget(card, placed / columns, placed % columns, Qt::AlignTop | Qt::AlignLeft);
        ++placed;
        m_lookCards << card;
        if (entryChosen(*e))
            card->setChecked(true);
    }
    // My Looks also opens Learn for references the person likes.
    if (m_filter == QLatin1String("mine")) {
        auto import = new LookCard(QStringLiteral("import"), tr("Learn a Look from videos I like..."),
                                   tr("Point letitedit at a few videos you like: it studies them on this computer and "
                                      "makes a personal Look here."),
                                   QString(), QString(), framedPicture(importPicture(), pictureSize), pictureSize, playback, m_styleHolder);
        import->setCheckable(false);
        import->setObjectName(QStringLiteral("newVideoStyle_import"));
        connect(import, &QPushButton::clicked, this, [this]() { importStyle(); });
        m_styleGrid->addWidget(import, placed / columns, placed % columns, Qt::AlignTop | Qt::AlignLeft);
        ++placed;
    }
    m_styleGrid->setColumnStretch(columns, 1);
    m_styleGrid->setRowStretch(placed / columns + 1, 1);
    m_filling = false;
    return shown;
}

} // namespace NewVideo
