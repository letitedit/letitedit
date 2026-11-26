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

// New video: the detailed settings' presets, My style and Import a style.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

namespace {
QString currentPresetId(const QString &identity)
{
    if (!identity.startsWith(QLatin1String("style:")))
        return identity;
    const QString look = MyStyle::legacyLook(identity.mid(6));
    return look.isEmpty() ? identity : QStringLiteral("look:") + look;
}
}


QJsonArray NewVideoDialog::storedPresets() const
{
    return QJsonDocument::fromJson(leSettings().value(QStringLiteral("firstCut/customPresets")).toByteArray()).array();
}

void NewVideoDialog::storePresets(const QJsonArray &presets)
{
    leSettings().setValue(QStringLiteral("firstCut/customPresets"), QJsonDocument(presets).toJson(QJsonDocument::Compact));
    leSettings().sync();
}

QJsonArray NewVideoDialog::allPresets() const
{
    QJsonArray result = storedPresets();
    const QStringList hidden = leSettings().value(QStringLiteral("firstCut/hiddenLegacyPresets")).toStringList();
    for (const auto &card : m_catalog) {
        if (!card.mine)
            continue;
        const QString id = QStringLiteral("look:%1").arg(card.name);
        if (hidden.contains(id))
            continue;
        bool found = false;
        for (const QJsonValue &entry : result)
            found |= entry.toObject().value(QStringLiteral("id")).toString() == id;
        if (!found)
            result.append(QJsonObject{{QStringLiteral("id"), id}, {QStringLiteral("name"), card.label},
                                      {QStringLiteral("look_id"), card.name}});
    }
    return result;
}

QJsonObject NewVideoDialog::selectedPreset() const
{
    const QString id = m_presetList->currentData().toString();
    for (const QJsonValue &entry : allPresets())
        if (entry.toObject().value(QStringLiteral("id")).toString() == id)
            return entry.toObject();
    return {};
}

void NewVideoDialog::fillPresets(const QString &select)
{
    const QSignalBlocker blocker(m_presetList);
    m_presetList->clear();
    m_presetList->addItem(tr("Choose a saved mix"), QString());
    const QString starred = leSettings().value(QStringLiteral("firstCut/customDefaultPreset")).toString();
    for (const QJsonValue &entry : allPresets()) {
        const QJsonObject preset = entry.toObject();
        const QString id = preset.value(QStringLiteral("id")).toString();
        const QString label = preset.value(QStringLiteral("name")).toString();
        m_presetList->addItem((currentPresetId(id) == currentPresetId(starred) ? QStringLiteral("★ ") : QString()) + label, id);
    }
    const QString wanted = select.isNull() ? starred : select;
    int index = m_presetList->findData(wanted);
    if (index < 0)
        index = m_presetList->findData(currentPresetId(wanted));
    m_presetList->setCurrentIndex(index >= 0 ? index : 0);
    loadSelectedPreset();
}

void NewVideoDialog::resetCustom(bool clearPreset)
{
    m_loadingPreset = true;
    m_master->setValue(3);
    m_masterAi->setChecked(true);
    for (auto it = m_sliders.cbegin(); it != m_sliders.cend(); ++it) {
        it.value()->setValue(3);
        m_aiSwitches.value(it.key())->setChecked(true);
    }
    m_legacyStyle.clear();
    if (clearPreset)
        m_presetList->setCurrentIndex(0);
    m_loadingPreset = false;
    if (clearPreset)
        m_presetNote->setText(tr("Each AI switch leaves that setting to your AI."));
}

void NewVideoDialog::loadSelectedPreset()
{
    if (m_loadingPreset)
        return;
    const QJsonObject preset = selectedPreset();
    resetCustom(false);
    const QJsonObject values = preset.value(QStringLiteral("sliders")).toObject();
    m_loadingPreset = true;
    for (auto it = values.begin(); it != values.end(); ++it) {
        if (m_sliders.contains(it.key())) {
            m_sliders.value(it.key())->setValue(qBound(0, it.value().toInt(3), 6));
            m_aiSwitches.value(it.key())->setChecked(false);
        }
    }
    m_legacyStyle = preset.value(QStringLiteral("look_id")).toString();
    if (m_legacyStyle.isEmpty()) {
        const QString legacy = preset.value(QStringLiteral("legacy_style")).toString();
        m_legacyStyle = MyStyle::legacyLook(legacy);
        if (m_legacyStyle.isEmpty())
            m_legacyStyle = legacy;
    }
    m_loadingPreset = false;
    m_presetName->setText(preset.value(QStringLiteral("name")).toString());
    m_presetNote->setText(m_legacyStyle.isEmpty()
                              ? tr("Only switched-off AI settings are saved in this mix.")
                              : tr("This uses your personal Look: %1. Moving a slider starts a new Custom mix.").arg(m_legacyStyle));
    const bool isDefault = !preset.isEmpty() && preset.value(QStringLiteral("id")).toString()
                           == currentPresetId(leSettings().value(QStringLiteral("firstCut/customDefaultPreset")).toString());
    m_defaultPresetButton->setText(isDefault ? tr("★ Default") : tr("☆ Default"));
}

void NewVideoDialog::saveCurrentPreset()
{
    const QString name = m_presetName->text().trimmed();
    if (name.isEmpty()) {
        m_presetNote->setText(tr("Type a name, then save this mix."));
        m_presetName->setFocus();
        return;
    }
    QJsonObject values;
    for (auto it = m_sliders.cbegin(); it != m_sliders.cend(); ++it)
        if (!m_aiSwitches.value(it.key())->isChecked())
            values.insert(it.key(), it.value()->value());
    const QString id = QStringLiteral("preset:%1").arg(QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMddhhmmsszzz")));
    QJsonArray presets = storedPresets();
    presets.append(QJsonObject{{QStringLiteral("id"), id}, {QStringLiteral("name"), name},
                               {QStringLiteral("sliders"), values}});
    storePresets(presets);
    fillPresets(id);
    m_presetNote->setText(tr("Saved %1. Pick it any time from this list.").arg(name));
}

void NewVideoDialog::renameSelectedPreset()
{
    const QJsonObject selected = selectedPreset();
    const QString name = m_presetName->text().trimmed();
    if (selected.isEmpty() || name.isEmpty()) {
        m_presetNote->setText(tr("Choose a saved mix and type its new name."));
        return;
    }
    QJsonArray presets = storedPresets();
    bool found = false;
    for (int i = 0; i < presets.size(); ++i) {
        QJsonObject item = presets[i].toObject();
        if (item.value(QStringLiteral("id")) == selected.value(QStringLiteral("id"))) {
            item.insert(QStringLiteral("name"), name);
            presets.replace(i, item);
            found = true;
            break;
        }
    }
    if (!found) {
        QJsonObject item = selected;
        item.insert(QStringLiteral("name"), name);
        presets.append(item);
    }
    storePresets(presets);
    fillPresets(selected.value(QStringLiteral("id")).toString());
}

void NewVideoDialog::deleteSelectedPreset()
{
    const QJsonObject selected = selectedPreset();
    if (selected.isEmpty())
        return;
    const QString id = selected.value(QStringLiteral("id")).toString();
    QJsonArray presets = storedPresets();
    for (int i = presets.size() - 1; i >= 0; --i)
        if (presets[i].toObject().value(QStringLiteral("id")).toString() == id)
            presets.removeAt(i);
    storePresets(presets);
    if (id.startsWith(QLatin1String("look:")) || id.startsWith(QLatin1String("style:"))) {
        QStringList hidden = leSettings().value(QStringLiteral("firstCut/hiddenLegacyPresets")).toStringList();
        hidden << id;
        leSettings().setValue(QStringLiteral("firstCut/hiddenLegacyPresets"), hidden);
    }
    if (currentPresetId(leSettings().value(QStringLiteral("firstCut/customDefaultPreset")).toString()) == id)
        leSettings().remove(QStringLiteral("firstCut/customDefaultPreset"));
    leSettings().sync();
    fillPresets(QString());
    m_presetNote->setText(tr("Removed from your saved mixes. Looks and videos you already made are not changed."));
}

void NewVideoDialog::starSelectedPreset()
{
    const QJsonObject selected = selectedPreset();
    if (selected.isEmpty()) {
        m_presetNote->setText(tr("Choose a saved mix to make it the default for Custom."));
        return;
    }
    const QString id = selected.value(QStringLiteral("id")).toString();
    if (currentPresetId(leSettings().value(QStringLiteral("firstCut/customDefaultPreset")).toString()) == id)
        leSettings().remove(QStringLiteral("firstCut/customDefaultPreset"));
    else
        leSettings().setValue(QStringLiteral("firstCut/customDefaultPreset"), id);
    leSettings().sync();
    fillPresets(id);
}

// A3 (the owner, 29 Oct): once the person has saved a My style, a new video starts with it (one click to "Let the AI
// decide"): the style used or saved last in My style, else the one saved most recently.
QString NewVideoDialog::mineByDefault()
{
    const QString identity = MyStyle::active();
    return MyStyle::styles().contains(identity) ? identity : QStringLiteral("none");
}

// "Make a style from videos I like...": the import, then its card appears here, chosen.
void NewVideoDialog::importStyle()
{
    LeFeatures::showLearn(m_window);
    loadLooks();
    loadStyles();
}

} // namespace NewVideo
