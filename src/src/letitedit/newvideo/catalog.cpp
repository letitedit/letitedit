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

// New video: the catalogue of content categories, Looks and Themes, and the person's own Looks.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// The picker's defaults, from the same Look library the AI reads; never blocks the steps.
void NewVideoDialog::loadStyles()
{
    const QString python = aiChatSettings().value("python").toString();
    auto process = new QProcess(this);
    connect(process, &QProcess::finished, this, [this, process](int code, QProcess::ExitStatus) {
        process->deleteLater();
        const QByteArray out = process->readAllStandardOutput();
        const QJsonObject catalog = QJsonDocument::fromJson(out.mid(out.indexOf('{'))).object();
        m_catalog.clear();
        for (const auto &v : catalog.value("looks").toArray()) {
            const QJsonObject card = v.toObject();
            if (card.contains("error") || card.value("id").toString().isEmpty())
                continue;
            StyleChoice c;
            c.name = card.value("id").toString();
            c.label = card.value("label").toString(c.name);
            c.summary = card.value("line").toString();
            c.kind = card.value("kind").toString(QStringLiteral("both"));
            for (const auto &t : card.value("tags").toArray())
                c.tags << t.toString();
            c.preview = card.value("preview").toString();
            c.recipe = card.value("recipe").toString();
            c.mine = card.value("personal").toBool();
            m_catalog << c;
        }
        m_catalogState = code == 0 && catalog.contains("looks") ? 1 : -1;
        refreshChoicePages();
    });
    connect(process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError e) {
        if (e == QProcess::FailedToStart) {
            m_catalogState = -1;
            refreshChoicePages();
        }
    });
    process->start(python, {aiRootPath(QStringLiteral("bridge/look_library.py")), QStringLiteral("--list-json")});
}

// The Styles that have Looks, from the same tool side as the style cards (bridge\looks.py --list-json reads
// looks\manifest.json), so adding or removing a Look needs no editor build. Never blocks the steps.
void NewVideoDialog::loadLooks()
{
    m_libraryStyles = qEnvironmentVariable("LETITEDIT_PICKER_LIBRARY_STYLES") == QLatin1String("1");
    const QString python = aiChatSettings().value("python").toString();
    auto process = new QProcess(this);
    connect(process, &QProcess::finished, this, [this, process](int code, QProcess::ExitStatus) {
        process->deleteLater();
        const QByteArray out = process->readAllStandardOutput();
        const QJsonObject catalog = QJsonDocument::fromJson(out.mid(out.indexOf('{'))).object();
        m_modern = catalog.value("layout_version").toInt() == 2;
        m_review = catalog.value("review_enabled").toBool();
        if (m_modern && m_music == QLatin1String("auto") && !m_song->text().trimmed().isEmpty()) {
            m_music = QStringLiteral("trending");
            m_musicFile = m_song->text().trimmed().remove(QLatin1Char('"'));
            m_song->clear();
        }
        m_themes = catalog.value("themes").toArray();
        m_reviewItems = catalog.value("review_items").toArray();
        m_lookStyles.clear();
        for (const auto &sv : catalog.value("styles").toArray()) {
            const QJsonObject s = sv.toObject();
            LookStyle style;
            style.id = s.value("id").toString();
            style.review = s.value("review").toString();
            style.cut = s.value("cut").toBool();
            style.label = s.value("label").toString(style.id);
            style.line = s.value("line").toString();
            style.kind = s.value("kind").toString(QStringLiteral("both"));
            style.footage = s.value("footage").toString(QStringLiteral("yes"));
            style.filterLabel = s.value("filter_label").toString(style.label);
            style.group = s.value("group").toString();
            style.hidden = s.value("hidden").toBool();
            style.filmed = s.value("filmed").toString();
            for (const auto &id : s.value("fitting").toArray())
                style.fitting << id.toString();
            for (const auto &fv : s.value("folders").toArray()) {
                const QJsonObject f = fv.toObject();
                LookFolder folder;
                folder.id = f.value("id").toString();
                folder.label = f.value("label").toString(folder.id);
                folder.line = f.value("line").toString();
                folder.poster = f.value("poster").toString();
                for (const auto &id : f.value("looks").toArray())
                    folder.looks << id.toString();
                if (!folder.id.isEmpty() && !folder.looks.isEmpty())
                    style.folders << folder;
            }
            for (const auto &lv : s.value("looks").toArray()) {
                const QJsonObject l = lv.toObject();
                LookChoice look;
                look.id = l.value("id").toString();
                look.themes = l.value("themes").toString(QStringLiteral("none"));
                look.review = l.value("review").toString();
                look.cut = l.value("cut").toBool();
                look.label = l.value("label").toString(look.id);
                look.line = l.value("line").toString();
                look.needs = l.value("needs").toString();
                look.preview = l.value("preview").toString();
                look.poster = l.value("poster").toString();
                look.previewLong = l.value("preview_long").toString();
                look.posterLong = l.value("poster_long").toString();
                look.posterAt = l.value("poster_s").toDouble();
                look.posterLongAt = l.value("poster_long_s").toDouble();
                look.folder = l.value("folder").toString();
                look.worksWith = l.value("works_with").toString(QStringLiteral("footage"));
                look.kind = l.value("kind").toString(QStringLiteral("both"));
                look.personal = l.value("personal").toBool();
                look.basedOn = l.value("based_on").toString();
                for (const auto &kind : l.value("fits").toArray())
                    look.fits << kind.toString();
                look.place = l.value("place").toString();
                for (const auto &av : l.value("asks").toArray()) {
                    const QJsonObject a = av.toObject();
                    LookAsk ask;
                    ask.id = a.value("id").toString();
                    ask.kind = a.value("kind").toString(QStringLiteral("text"));
                    ask.label = a.value("label").toString(ask.id);
                    ask.hint = a.value("hint").toString();
                    ask.need = a.value("need").toString(QStringLiteral("optional"));
                    ask.role = a.value("role").toString(ask.id);
                    ask.instead = a.value("instead").toString();
                    if (!ask.id.isEmpty())
                        look.asks << ask;
                }
                if (!look.id.isEmpty())
                    style.looks << look;
            }
            if (!style.id.isEmpty() && (m_modern || !style.looks.isEmpty()))
                m_lookStyles << style;
        }
        mergePersonalLooks();
        if (m_modern && (m_style == QLatin1String("made-with-code") || m_style == QLatin1String("idea")))
            m_style = QStringLiteral("none");
        if (!m_selectLook.isEmpty()) {
            // a Look just learned or adjusted becomes the chosen one
            for (const auto &candidate : std::as_const(m_lookStyles))
                if (findLook(candidate, m_selectLook)) {
                    if (m_style != candidate.id) {
                        m_style = candidate.id;
                        m_browseStyle = candidate.id;
                    }
                    m_look = m_selectLook;
                    m_theme = QStringLiteral("freestyle");
                    m_themeChosen = false;
                    m_personChose = true;
                    m_styleExplicit = true;
                    break;
                }
            m_selectLook.clear();
        }
        const QJsonObject picker = catalog.value("picker").toObject();
        m_libraryStyles = m_libraryStyles || picker.value("library_styles").toBool();
        m_alsoShow.clear();
        for (const auto &n : picker.value("also_show").toArray())
            m_alsoShow << n.toString();
        m_looksState = code == 0 && catalog.contains("styles") ? 1 : -1;
        // a draft from before these three stages: a no-footage Look chosen means no footage
        if (!m_routeRemembered && m_personChose && !m_noFootage)
            if (const LookChoice *look = chosenLookCard())
                if (look->worksWith == QLatin1String("no-footage")) {
                    QScopedValueRollback<bool> restoringRoute(m_restoringRoute, true);
                    m_noFootageButton->setChecked(true);
                }
        refreshChoicePages();
    });
    connect(process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError e) {
        if (e == QProcess::FailedToStart) {
            m_looksState = -1;
            refreshChoicePages();
        }
    });
    process->start(python, {aiRootPath(QStringLiteral("bridge/looks.py")), QStringLiteral("--list-json")});
}

// The person's own Looks come in a group of their own from the catalogue; each is shown under the Style it suits: an
// adjusted Look under its base Look's Style, a learned one under the first offered kind of video it fits (Learn saves
// them in `fits`; the Look step's tabs show it under the others too). A Look saved before kinds: under Talking head
// (no-footage ones under the first shown 100% AI Style), as before. A Look that works both with and without footage
// is placed once for each, so both routes offer it; a hidden or cut Style never takes one
void NewVideoDialog::mergePersonalLooks()
{
    int personalIndex = -1;
    for (int i = 0; i < m_lookStyles.size(); ++i)
        if (m_lookStyles[i].id == QLatin1String("personal-looks"))
            personalIndex = i;
    if (personalIndex < 0)
        return;
    const QList<LookChoice> mine = m_lookStyles[personalIndex].looks;
    m_lookStyles.removeAt(personalIndex);
    for (const LookChoice &look : mine) {
        QList<bool> routes; // true: the 100% AI route
        if (look.worksWith != QLatin1String("no-footage"))
            routes << false;
        if (look.worksWith == QLatin1String("no-footage") || look.worksWith == QLatin1String("both"))
            routes << true;
        for (const bool noFootage : std::as_const(routes)) {
            const auto offered = [&](const LookStyle &candidate) {
                return !candidate.hidden && (!candidate.cut || m_review)
                       && (candidate.footage == QLatin1String("no")) == noFootage;
            };
            int target = -1;
            if (!look.basedOn.isEmpty())
                for (int i = 0; i < m_lookStyles.size() && target < 0; ++i)
                    if (findLook(m_lookStyles[i], look.basedOn)
                        && (m_lookStyles[i].footage == QLatin1String("no")) == noFootage)
                        target = i;
            for (const QString &kind : look.fits)
                for (int i = 0; i < m_lookStyles.size() && target < 0; ++i)
                    if (m_lookStyles[i].id == kind && offered(m_lookStyles[i]))
                        target = i;
            for (int i = 0; i < m_lookStyles.size() && target < 0; ++i) {
                const LookStyle &candidate = m_lookStyles[i];
                if (noFootage ? offered(candidate) : candidate.id == QLatin1String("talking-head"))
                    target = i;
            }
            if (target >= 0) {
                LookChoice placed = look;
                placed.personal = true;
                m_lookStyles[target].looks << placed;
            }
        }
    }
}

const LookChoice *NewVideoDialog::findLook(const LookStyle &style, const QString &id) const
{
    for (const auto &look : style.looks)
        if (look.id == id)
            return &look;
    return nullptr;
}

const LookFolder *NewVideoDialog::lookFolder(const LookStyle &style, const QString &id) const
{
    if (id.isEmpty())
        return nullptr;
    for (const auto &folder : style.folders)
        if (folder.id == id)
            return &folder;
    return nullptr;
}

const LookStyle *NewVideoDialog::lookStyle(const QString &id) const
{
    for (const auto &s : m_lookStyles)
        if (s.id == id)
            return &s;
    return nullptr;
}

} // namespace NewVideo
