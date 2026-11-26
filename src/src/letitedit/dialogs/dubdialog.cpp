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

// Dub this video: the language and voice, then the request to the AI.
// (Split out of lefeatures.cpp; what it shares with it is in featurehelpers.h.)

#include "featurehelpers.h"

namespace LeFeatures {

namespace {

class DubDialog : public QDialog
{
public:
    explicit DubDialog(MainWindow *window)
        : QDialog(window)
    {
        setObjectName(QStringLiteral("dubDialog"));
        setWindowTitle(tr("Dub this video"));
        setMinimumWidth(520);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        column->addWidget(headingLabel(tr("Dub this video into another language"), this));
        column->addWidget(mutedLabel(tr("Your AI translates what's said, line by line, and a voice on this computer speaks "
                                        "it in time with the video, on its own track. Your original stays as it is: "
                                        "Undo takes the dub back."),
                                     this));
        auto form = new QFormLayout;
        m_language = new QComboBox(this);
        m_language->setObjectName(QStringLiteral("dubLanguage"));
        const QList<QPair<QString, QString>> languages{{tr("Spanish"), "es"},       {tr("French"), "fr"},
                                                       {tr("Italian"), "it"},       {tr("Portuguese"), "pt"},
                                                       {tr("Hindi"), "hi"},         {tr("Japanese"), "ja"},
                                                       {tr("Chinese"), "zh"},       {tr("English (US)"), "en"},
                                                       {tr("English (UK)"), "en-gb"}};
        for (const auto &l : languages)
            m_language->addItem(l.first, l.second);
        m_language->setCurrentIndex(qMax(0, m_language->findData(leSettings().value("dub/language", "es").toString())));
        form->addRow(tr("Into"), m_language);
        m_voice = new QComboBox(this);
        m_voice->setObjectName(QStringLiteral("dubVoice"));
        m_voice->addItem(tr("A man's voice"), QStringLiteral("male"));
        m_voice->addItem(tr("A woman's voice"), QStringLiteral("female"));
        m_voice->setCurrentIndex(qMax(0, m_voice->findData(leSettings().value("dub/gender", "male").toString())));
        form->addRow(tr("Voice"), m_voice);
        m_original = new QComboBox(this);
        m_original->setObjectName(QStringLiteral("dubOriginal"));
        m_original->addItem(tr("Quieter underneath (recommended)"), QStringLiteral("lower"));
        m_original->addItem(tr("Silent"), QStringLiteral("mute"));
        m_original->addItem(tr("Keep it as it is"), QStringLiteral("keep"));
        form->addRow(tr("Your own voice"), m_original);
        column->addLayout(form);
        column->addWidget(mutedLabel(tr("The first dub downloads the voices (about 330 MB). Captions aren't changed: use "
                                        "Translate captions for those."),
                                     this));
        auto buttons = new QDialogButtonBox(QDialogButtonBox::Cancel, this);
        auto go = buttons->addButton(tr("Dub it"), QDialogButtonBox::AcceptRole);
        go->setObjectName(QStringLiteral("dubGo"));
        go->setDefault(true);
        connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
        connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
        column->addWidget(buttons);
    }

    QString language() const { return m_language->currentData().toString(); }
    QString languageName() const { return m_language->currentText(); }
    QString gender() const { return m_voice->currentData().toString(); }
    QString original() const { return m_original->currentData().toString(); }

private:
    QComboBox *m_language = nullptr;
    QComboBox *m_voice = nullptr;
    QComboBox *m_original = nullptr;
};

} // namespace

void showDub(MainWindow *window)
{
    if (!window->multitrack()) {
        window->showStatusMessage(QObject::tr("Put your video on the timeline first, then dub it."), 10);
        return;
    }
    if (window->fileName().isEmpty()) {
        QMessageBox::information(window, QObject::tr("Dub this video"),
                                 QObject::tr("Save your video first (Menu > File > Save): your AI dubs the saved "
                                             "project. Then press Dub this video again."));
        return;
    }
    DubDialog dialog(window);
    if (dialog.exec() != QDialog::Accepted)
        return;
    leSettings().setValue("dub/language", dialog.language());
    leSettings().setValue("dub/gender", dialog.gender());
    const QString text
        = QObject::tr("Dub my open project %1 into %2: get the lines with letitedit_dub_lines(project), translate each "
                      "line into %2 keeping it about as long as the original (names, brands and part numbers as they "
                      "are), then letitedit_dub(project, language='%3', lines=<the translated lines with their start "
                      "and end>, gender='%4', original_voice='%5'). It is one Undo step. Don't change the captions. "
                      "Reply in one or two lines when it's done, and say if any line ran long.")
              .arg(nativePath(window->fileName()), dialog.languageName(), dialog.language(), dialog.gender(),
                   dialog.original());
    ask(window, text, QObject::tr("Dub this video into %1").arg(dialog.languageName()),
        QObject::tr("Your AI is dubbing the video into %1; a Dub track appears when it's done.").arg(dialog.languageName()));
}

} // namespace LeFeatures
