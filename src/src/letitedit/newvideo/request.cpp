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

// New video: what is sent to the AI when the person presses Go.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

#include <QCryptographicHash>
#include <QSaveFile>

namespace {

// T331 P4: keep the typed request beside the video (new-video-request.json). On by default (T365):
// LETITEDIT_TYPED_NEW_VIDEO_REQUEST (1 or 0) wins, else settings.json typed_new_video_request (false turns it off).
bool typedRequestOn()
{
    const QString forced = qEnvironmentVariable("LETITEDIT_TYPED_NEW_VIDEO_REQUEST").trimmed().toLower();
    if (forced == QLatin1String("1") || forced == QLatin1String("true") || forced == QLatin1String("on")
        || forced == QLatin1String("yes"))
        return true;
    if (forced == QLatin1String("0") || forced == QLatin1String("false") || forced == QLatin1String("off")
        || forced == QLatin1String("no"))
        return false;
    const QString path = qEnvironmentVariableIsSet("LETITEDIT_SETTINGS") ? qEnvironmentVariable("LETITEDIT_SETTINGS")
                                                                        : aiRootPath(QStringLiteral("settings.json"));
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return true;
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    return QJsonDocument::fromJson(data).object().value(QStringLiteral("typed_new_video_request")).toBool(true);
}

} // namespace

QString firstCutRequest(const QString &folder,
                        const QString &kind,
                        const QString &length,
                        const QString &about,
                        const QString &style,
                        const QString &styleLabel,
                        bool mine,
                        const QString &custom,
                        const QStringList &files,
                        const QString &look,
                        const QString &lookLabel,
                        const QString &styleKindLabel,
                        const QString &inputs,
                        bool noFootage,
                        bool turbo)
{
    const QString duration = length.isEmpty() ? QStringLiteral("the length the AI chooses") : QStringLiteral("about %1").arg(length);
    const QString what
        = kind == QLatin1String("short")
              ? QStringLiteral("a vertical short of %1 (1080x1920, for TikTok, Shorts and Reels)").arg(duration)
          : kind == QLatin1String("long")
              ? QStringLiteral("a YouTube video of %1 (1920x1080)").arg(duration)
          : kind == QLatin1String("custom")
              ? QStringLiteral("what I describe here: \"%1\" (%2; choose the shape that suits it)").arg(custom.trimmed(), duration)
              : QStringLiteral("both: a vertical short (1080x1920) and a YouTube video (1920x1080), each %1").arg(duration);
    QString source = files.isEmpty() ? QStringLiteral("the folder %1").arg(QDir::toNativeSeparators(folder))
                                     : QStringLiteral("these files: %1").arg(files.join(QStringLiteral("; ")));
    if (turbo) {
        // Turbo (T80): a short request of its own. One skill, no router, no stage skills, no recipe to read, no "why"
        // markers and no hook candidates: the person asked for speed, and each of those is minutes
        QString quick = noFootage
            ? QStringLiteral("Make a first cut with no footage in Turbo mode: this Look draws everything itself. Read only the "
                             "`letitedit-turbo` skill and the chosen Look's own recipe: they take the place of the `letitedit` router, "
                             "`letitedit-firstcut` and every stage skill.\n\nWhat to make: %1.\n").arg(what)
            : QStringLiteral("Make a first cut from %1 in Turbo mode. Read only the `letitedit-turbo` skill (and the chosen Look's own "
                             "recipe, if it isn't Clean): they take the place of the `letitedit` router, `letitedit-firstcut` and every "
                             "stage skill.\n\nWhat to make: %2.\n").arg(source, what);
        quick += length.isEmpty() ? QStringLiteral("Length: Let the AI choose.\n")
                                  : QStringLiteral("Length: %1.\n").arg(length);
        if (!look.isEmpty())
            quick += QStringLiteral("look: %1\n").arg(look);
        else if (style.isEmpty() || style == QLatin1String("none"))
            quick += QStringLiteral("look: none\n");
        else
            quick += QStringLiteral("look: %1\n").arg(style);
        if (!about.trimmed().isEmpty())
            quick += QStringLiteral("What it's about, and what must stay in or stay out: %1\n").arg(about.trimmed());
        quick += QStringLiteral("turbo: on\n(I turned on Turbo, which sacrifices quality for speed on this first run through only. "
                                "I'm putting speed over quality: keep every scene, card, effect and graphic very simple and brief, "
                                "draw each once, check nothing twice, and finish. It never changes your AI, model or effort. Tell me at "
                                "the end that Turbo was on and what it skipped. Notes I send afterwards are handled as normal.)\n");
        if (!inputs.isEmpty())
            quick += QLatin1Char('\n') + inputs;
        quick += QStringLiteral("\nWhen the first cut is done, open it for me and tell me in two lines what you made and what Turbo skipped. "
                                "Do not call it ready without a ready review verdict.");
        return quick;
    }
    QString text = noFootage
        ? QStringLiteral("Make a first cut with no footage: this Look draws everything itself (use the letitedit skills: the "
                         "`letitedit` router and `letitedit-firstcut`).\n\nWhat to make: %1.\n").arg(what)
        : QStringLiteral("Make a first cut from %1 (use the letitedit skills: the `letitedit` "
                         "router and `letitedit-firstcut`).\n\nWhat to make: %2.\n")
              .arg(source, what);
    text += length.isEmpty() ? QStringLiteral("Length: Let the AI choose.\n")
                             : QStringLiteral("Length: %1.\n").arg(length);
    // the brief's style field as its own line (STYLES.md 5.1), then what it means
    if (!look.isEmpty()) {
        // a Style with Looks (Talking head): no style pack, a `look` line (the router's brief field) instead
        text += QStringLiteral("look: %1\n").arg(look);
        if (look == QLatin1String("auto"))
            text += QStringLiteral("(I chose the Style \"%1\" and \"Let the AI pick\" for its Look: choose one of its Looks "
                                   "for this footage with letitedit_looks(action: \"list\"), from each one's \"needs\" "
                                   "line, and tell me which you chose and why before you start.)\n")
                        .arg(styleKindLabel);
        else if (look == QLatin1String("freestyle"))
            text += QStringLiteral("(I chose Freestyle: no set Look. Work out the kind of video from the footage and edit it the "
                                   "way that suits the clips, as the `letitedit` router's `look` field says for freestyle: "
                                   "there is no Look recipe to read, and `look` stays out of brief.json.)\n");
        else
            text += QStringLiteral("(I chose the Style \"%1\" and its Look \"%2\". A Look is a recipe to work from, not a "
                                   "template: read it in full with letitedit_looks(action: \"get\", id: %3), as the `letitedit` router's "
                                   "`look` field says, and keep the brief's look: %3 so the review judges the video "
                                   "against it.)\n")
                        .arg(styleKindLabel, lookLabel.isEmpty() ? look : lookLabel, look);
    } else if (style.isEmpty() || style == QLatin1String("none"))
        text += QStringLiteral("look: none\n(I chose \"Let the AI decide\": neutral defaults and your editing skills.)\n");
    else
        text += QStringLiteral("look: %2\n(I chose the Look \"%1\"%3: select it with {op: look, id: %2}; "
                               "letitedit_looks(action: \"get\", id: %2) reads its recipe and settings.)\n")
                     .arg(styleLabel.isEmpty() ? style : styleLabel, style,
                          mine ? QStringLiteral(", my personal Look") : QString());
    if (!about.trimmed().isEmpty())
        text += QStringLiteral("What it's about, and what must stay in or stay out: %1\n").arg(about.trimmed());
    if (!inputs.isEmpty())
        text += QLatin1Char('\n') + inputs;
    text += QStringLiteral("\nWhen the cut is done, open it for me. State the review verdict and link its plain review line; "
                           "only call the video ready when the review verdict is ready. Tell me the story in two lines and put a one-line "
                           "\"why\" marker on every clip. Put the strongest opening first. I try other openings with "
                           "the app's New hook button (hook candidates from letitedit_hooks, kept beside the project), "
                           "so don't make copies of the project for other openings: if you have better opening ideas "
                           "than its candidates, add them as hook candidates. I'll tell you what to change.");
    return text;
}

namespace NewVideo {

void NewVideoDialog::send()
{
    if (!prepareRequest())
        return;
    const bool waitingForLook = m_look == QLatin1String("pending-learn");
    QString label;
    bool mine = false;
    if (const StyleChoice *c = chosenCatalogCard()) {
        label = c->label;
        mine = c->mine;
    }
    if (m_style == QLatin1String("custom")) {
        if (!writeCustomStyle())
            return;
        label = m_style == QLatin1String("none") ? tr("Let the AI decide")
                : m_legacyStyle.isEmpty() ? tr("Custom") : m_presetName->text().trimmed();
        mine = !m_legacyStyle.isEmpty();
    }
    if (m_modern && m_caption == QLatin1String("custom")) {
        const QString selectedStyle = m_style;
        m_style = QStringLiteral("custom");
        const bool written = writeCustomStyle();
        m_caption = m_style;
        m_style = selectedStyle;
        if (!written)
            return;
    }
    const QString path = m_folder->text().trimmed();
    // a Style with Looks (Talking head) sends its Look instead of a style pack
    const LookStyle *looks = lookStyle(m_style);
    QString look, lookLabel, styleKindLabel;
    if (looks) {
        look = waitingForLook ? QStringLiteral("@@LOOK_ID@@") : m_look;
        lookLabel = waitingForLook ? QStringLiteral("@@LOOK_NAME@@") : currentLookLabel(*looks);
        const LookStyle *filmed = lookStyle(filmedStyle()); // T179: the Style is what was filmed (the tab)
        styleKindLabel = filmed ? filmed->label : tr("All");
    }
    // the Look's boxes (T64): every required one filled; the answers are written as a record the AI, the review and
    // later rounds read
    QString inputsText, recordPath;
    bool noFootage = m_noFootage;
    if (looks)
        if (const LookChoice *chosen = findLook(*looks, m_look))
            noFootage = noFootage || chosen->worksWith == QLatin1String("no-footage");
    if (const LookChoice *asking = askingLook()) {
        if (asking->id != m_inputsLookId) { // never seen: show them
            go(PGo);
            return;
        }
        const QString missing = missingInputsLine();
        if (!missing.isEmpty()) {
            go(PGo);
            m_problem->setText(missing);
            m_problem->show();
            return;
        }
        const QJsonObject record = inputsRecord(*asking);
        recordPath = writeInputsRecord(record);
        if (recordPath.isEmpty()) {
            m_problem->setText(tr("Couldn't keep your answers for the AI. Press Make my video again in a moment."));
            m_problem->show();
            return;
        }
        inputsText = inputsRequestText(record, recordPath);
    }
    QString request = firstCutRequest(path,
                                            m_kind,
                                            m_aiLength->isChecked() ? QString() : normalizedLength(),
                                            m_about->toPlainText(),
                                            looks ? QStringLiteral("none") : m_style,
                                            looks ? QString() : label,
                                            mine,
                                            m_custom->toPlainText(),
                                            noFootage ? QStringList() : m_selectedFiles,
                                            look,
                                            lookLabel,
                                            styleKindLabel,
                                            inputsText,
                                            noFootage,
                                            m_turbo && m_turbo->isChecked());
    appendLookRequest(request, looks, noFootage, waitingForLook, look, lookLabel);
    const QString song = m_song && (!m_modern || m_music == QLatin1String("auto"))
                             ? m_song->text().trimmed().remove(QLatin1Char('"')) : QString();
    if (!song.isEmpty())
        request += QStringLiteral("\nsong: %1\nCut the video to this song. I add it in the phone app when I post, so the file I "
                                  "upload has none of it (the `song` field of the `letitedit` router, letitedit-sound section "
                                  "13). You pick the part; nothing more will be asked.\n")
                       .arg(song);
    // the chat shows a short line; the AI gets the whole brief
    const QString what = m_kind == QLatin1String("short")  ? tr("a vertical short")
                         : m_kind == QLatin1String("long") ? tr("a YouTube video")
                         : m_kind == QLatin1String("custom") ? tr("the video I described")
                                                              : tr("a short and a YouTube video");
    const QString styleWords = looks ? tr("%1, Look: %2").arg(styleKindLabel, lookLabel)
                               : (m_style.isEmpty() || m_style == QLatin1String("none") || label.isEmpty())
                                   ? tr("the AI picks the Look")
                                   : tr("Look: %1").arg(label);
    QString summary = noFootage ? tr("Make my first cut: %1, drawn by code with no footage (%2)").arg(what, styleWords)
                                : tr("Make my first cut: %1 from “%2” (%3)")
                                      .arg(what, QFileInfo(path).fileName(), styleWords);
    if (m_turbo && m_turbo->isChecked())
        summary += tr(" - Turbo on: sacrifices quality for speed");
    const QString videoName = waitingForLook ? m_pendingLearnName
                              : noFootage && m_look == QLatin1String("freestyle") ? tr("My video")
                              : noFootage ? (lookLabel.isEmpty() ? label : lookLabel)
                                       : m_selectedFiles.size() == 1 ? QFileInfo(m_selectedFiles.first()).completeBaseName()
                                                                    : QFileInfo(path).fileName();
    const QString saveFolder = VideoProjects::create(videoName);
    if (saveFolder.isEmpty()) {
        m_problem->setText(tr("Couldn't make a folder for this video. Choose a writable Projects folder in Settings."));
        m_problem->show();
        return;
    }
    request += QStringLiteral("\nSave video in: %1\nKeep the project, exports and AI working files in this folder. Reference the footage where it is; never copy or move it.\n")
                   .arg(QDir::fromNativeSeparators(saveFolder));
    if (typedRequestOn()) {
        // a file beside the video, written before the request goes; a failure to write it never stops the video
        const LookChoice *asking = recordPath.isEmpty() ? nullptr : askingLook();
        QJsonObject typed = typedRequest(path, looks, label, mine, look, lookLabel, styleKindLabel, noFootage, waitingForLook,
                                         asking ? inputsRecord(*asking) : QJsonObject(), recordPath, song, saveFolder);
        typed.insert("origin", "editor");
        typed.insert("text", request);
        typed.insert("summary", summary);
        typed.insert("text_sha256",
                     QString::fromLatin1(QCryptographicHash::hash(request.toUtf8(), QCryptographicHash::Sha256).toHex()));
        typed.insert("written", QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
        QSaveFile out(QDir(saveFolder).filePath(QStringLiteral("new-video-request.json")));
        if (out.open(QIODevice::WriteOnly)) {
            out.write(QJsonDocument(typed).toJson(QJsonDocument::Indented));
            out.commit();
        }
    }
    bool sent = true;
    if (waitingForLook) {
        // sent by the home page's timer once the Look is saved and the AI is free (learnlooks.h)
        const QString pendingPath = QFileInfo(m_pendingLearnJob).dir().filePath(QStringLiteral("pending-video.json"));
        sent = LearnLooks::writeJob(pendingPath, QJsonObject{{"request", request}, {"summary", summary}, {"folder", saveFolder}});
    } else {
        m_window->setProperty("letitedit:newVideoFolder", saveFolder);
        sent = aiChatRequest(m_window, request, summary, false, true);
    }
    if (!sent) {
        QFile::remove(QDir(saveFolder).filePath(QStringLiteral("new-video-request.json")));
        QDir().rmdir(saveFolder);
        const QString why = aiChatRefusal();
        m_problem->setText(!why.isEmpty() ? why
                                          : tr("Your AI couldn't take the request just now. Press Make my video again in a moment: "
                                               "everything here stays filled in."));
        m_problem->show();
        return;
    }
    {
        // T202: the person's own words in this request, kept in the video's folder before its project exists (actor person,
        // kind said), so a Look made from this video can keep their "always ..." and "never ..." about style
        const QString own = QStringList{m_about->toPlainText().trimmed(), m_custom->toPlainText().trimmed()}
                                .filter(QRegularExpression(QStringLiteral("\\S"))).join(QLatin1Char('\n'));
        if (!own.isEmpty())
            QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(),
                                    {aiRootPath(QStringLiteral("bridge/project_look.py")), QStringLiteral("said"),
                                     QStringLiteral("--folder"), QDir::toNativeSeparators(saveFolder), QStringLiteral("--where"),
                                     QStringLiteral("new video request"), QStringLiteral("--"), own.left(4000)});
    }
    if (!recordPath.isEmpty())
        keepInputsBesideProject(recordPath);
    clearSentRequest();
    if (waitingForLook) {
        m_window->showStatusMessage(tr("Your video starts as soon as “%1” is learned. It is waiting for it, and you can keep working.").arg(m_pendingLearnName), 15);
    } else {
        m_window->setProperty("letitedit:firstCutSent", QDateTime::currentDateTime());
        m_window->showStatusMessage(tr("Your AI is making the first cut. Follow along in the chat."), 10);
    }
    QDialog::accept();
}

bool NewVideoDialog::prepareRequest()
{
    for (int step : {int(PFormat), int(PContent), int(PLook), int(PGo)})
        if (!check(step)) {
            const QString why = m_problem->text();
            go(step);
            m_problem->setText(why);
            m_problem->show();
            return false;
        }
    checkFit();
    if (m_fit) {
        m_fitWaitingToSend = true;
        go(PGo);
        m_problem->setText(tr("The Look fit check is still running. Its result appears here; then press Make my video again."));
        m_problem->show();
        return false;
    }
    settleTheme();
    // a Look still being learned: the video waits for it and starts by itself. With no learn to wait for (its file is
    // gone), the AI picks the Look now rather than the video waiting for nothing (T167)
    if (m_look == QLatin1String("pending-learn") && !QFileInfo(m_pendingLearnJob).isFile()) {
        m_look = QStringLiteral("auto");
        m_pendingLearnJob.clear();
        m_pendingLearnName.clear();
    }
    remember();
    const bool waitingForLook = m_look == QLatin1String("pending-learn");
    if (!waitingForLook && aiChatState().value(QStringLiteral("busy")).toBool()) {
        m_problem->setText(tr("Your AI is still answering the last request. Wait for it to finish (or press Stop in "
                              "the chat), then press Make my video again. Everything here stays filled in."));
        m_problem->show();
        return false;
    }
    return true;
}

void NewVideoDialog::appendLookRequest(QString &request, const LookStyle *looks, bool noFootage, bool waitingForLook,
                                       const QString &look, const QString &lookLabel)
{
    for (const auto &file : lookArtifacts())
        request += QStringLiteral("\nLook file: %1\n").arg(file);
    if (m_modern) {
        // T179: Style is what was filmed: the tab, set from the clips or by the person (none for All with no answer)
        if (const LookStyle *filmed = looks ? lookStyle(filmedStyle()) : nullptr)
            request += QStringLiteral("\nStyle: %1 (%2)\n").arg(filmed->label, filmed->id);
        // T188: several cameras on one conversation (what_was_filmed): say so, so the AI syncs and cuts between them
        if (!noFootage && m_detectedAngles && detectKey() == m_detectedFor)
            request += QStringLiteral("\nThe clips look like several cameras filming one conversation (one shows both "
                                      "people, the others one face each): sync them by their sound (letitedit_sync), find "
                                      "who talks when (letitedit_speakers), then cut between the cameras on who talks "
                                      "({op: multicam}), as letitedit-firstcut's FIRST-1m says.\n");
        if (looks && m_look == QLatin1String("auto")) {
            QStringList shown;
            for (const auto &one : pickLooks())
                shown << one.second->id;
            if (!shown.isEmpty())
                request += QStringLiteral("\nLet the AI pick chooses one of the Looks I was shown: %1\n").arg(shown.join(QStringLiteral(", ")));
        }
        if (looks && (waitingForLook || (m_look != QLatin1String("auto") && !m_look.isEmpty())))
            request += QStringLiteral("\nLook: %1 (%2)\n").arg(lookLabel, look);
        // T174: the Look step's fit check of these clips against the learned Look's format, and the person's way out
        const LookChoice *fitCard = looks && !noFootage ? chosenLookCard() : nullptr;
        if (fitCard && !fitCard->place.isEmpty() && m_fitFor == fitCard->place + QLatin1Char('#') + detectKey() + QLatin1Char('#') + m_kind
            && !m_fitVerdict.isEmpty()) {
            request += QStringLiteral("\nFormat fit (letitedit's fit check of these clips against the Look's format): %1. %2\n")
                           .arg(m_fitVerdict, m_fitLine);
            if (m_fitVerdict == QLatin1String("no") && m_lookOnly && m_lookOnly->isChecked())
                request += QStringLiteral("\nLook use: look only. These clips don't fit this Look's format, and I chose to make it "
                                          "with only the look: keep its captions, graphics, colour and pace, and cut the clips the "
                                          "way they suit (format.fit look-only).\n");
        }
        request += themeRequest(chosenLookCard());
        request += QStringLiteral("\nFormat: %1\n").arg(m_kind == QLatin1String("long") ? QStringLiteral("YouTube video") : QStringLiteral("Short"));
        if (noFootage && m_references && m_references->count() > 0)
            request += QStringLiteral("\nReferences I added (characters, a logo, photos or a script to use in the video; read them, never change or move them): %1\n")
                           .arg(m_references->files().join(QStringLiteral("; ")));
        if (m_caption != QLatin1String("auto"))
            request += QStringLiteral("\nCaptions & pace: %1\n").arg(m_caption);
        if (m_music != QLatin1String("auto"))
            request += QStringLiteral("\nMusic: %1\n").arg(m_music);
        if (!m_musicFile.isEmpty() && (m_music == QLatin1String("own") || m_music == QLatin1String("trending")))
            request += QStringLiteral("Music file: %1\n").arg(m_musicFile);
    }
}

// the Look's own files the request names (a Custom Look's recipe and settings, a catalogue card's recipe)
QStringList NewVideoDialog::lookArtifacts() const
{
    QStringList artifacts = m_customArtifacts.value(m_style);
    if (artifacts.isEmpty()) {
        if (const StyleChoice *card = chosenCatalogCard(); card && !card->recipe.isEmpty())
            artifacts << card->recipe;
    }
    artifacts.append(m_customArtifacts.value(m_caption));
    artifacts.removeDuplicates();
    artifacts.removeAll(QString());
    return artifacts;
}

// T331 P4: the request as typed fields, resolved as send() resolves them (format letitedit-new-video-request/1). The
// fields are what firstCutRequest and appendLookRequest read; bridge/letitedit/app/new_video_request.py renders the same
// text from them, and the record keeps the text sent, so a difference is found, never hidden.
QJsonObject NewVideoDialog::typedRequest(const QString &path, const LookStyle *looks, const QString &label, bool mine,
                                         const QString &look, const QString &lookLabel, const QString &styleKindLabel,
                                         bool noFootage, bool waitingForLook, const QJsonObject &inputs,
                                         const QString &recordPath, const QString &song, const QString &saveFolder) const
{
    const auto strings = [](const QStringList &list) { return QJsonArray::fromStringList(list); };
    QJsonObject typed{{"format", "letitedit-new-video-request/1"},
                      {"kind", m_kind},
                      {"custom", m_custom->toPlainText()},
                      {"length", m_aiLength->isChecked() ? QString() : normalizedLength()},
                      {"about", m_about->toPlainText()},
                      {"turbo", m_turbo && m_turbo->isChecked()},
                      {"no_footage", noFootage},
                      {"footage", QJsonObject{{"folder", path}, {"files", strings(noFootage ? QStringList() : m_selectedFiles)}}},
                      {"look", QJsonObject{{"has_looks", looks != nullptr},
                                           {"style", looks ? QStringLiteral("none") : m_style},
                                           {"style_label", looks ? QString() : label},
                                           {"mine", mine},
                                           {"id", look},
                                           {"label", lookLabel},
                                           {"style_kind_label", styleKindLabel},
                                           {"files", strings(lookArtifacts())},
                                           {"waiting_for_learn", waitingForLook}}},
                      {"modern", m_modern},
                      {"captions", m_caption},
                      {"music", m_music},
                      {"music_file", m_musicFile},
                      {"song", song},
                      {"save_folder", QDir::fromNativeSeparators(saveFolder)}};
    if (!recordPath.isEmpty()) {
        // the boxes as inputsRequestText reads them, with what the Look says to do when one is left empty
        QJsonArray boxes;
        QSet<QString> roles;
        for (const auto &bv : inputs.value("inputs").toArray()) {
            const QJsonObject box = bv.toObject();
            QJsonObject one{{"id", box.value("id")},
                            {"kind", box.value("kind")},
                            {"role", box.value("role")},
                            {"label", box.value("label")},
                            {"instead", m_askDefs.value(box.value("id").toString()).instead}};
            roles.insert(box.value("role").toString());
            if (box.value("kind").toString() == QLatin1String("text")) {
                one.insert("text", box.value("text").toString());
            } else {
                QJsonArray files;
                for (const auto &fv : box.value("files").toArray())
                    files.append(fv.toObject().value("path").toString());
                one.insert("files", files);
            }
            boxes.append(one);
        }
        QJsonArray meanings; // in the order inputsRequestText writes them
        for (const QString &role : roles)
            if (!roleMeaning(role).isEmpty())
                meanings.append(QJsonArray{role, roleMeaning(role)});
        typed.insert("inputs", QJsonObject{{"record_path", recordPath}, {"boxes", boxes}, {"meanings", meanings}});
    }
    QJsonArray shown, references;
    QJsonValue filmedStyleValue(QJsonValue::Null), fit(QJsonValue::Null);
    bool multicam = false, lookLine = false;
    if (m_modern) {
        if (const LookStyle *filmed = looks ? lookStyle(filmedStyle()) : nullptr)
            filmedStyleValue = QJsonObject{{"id", filmed->id}, {"label", filmed->label}};
        multicam = !noFootage && m_detectedAngles && detectKey() == m_detectedFor;
        if (looks && m_look == QLatin1String("auto"))
            for (const auto &one : pickLooks())
                shown.append(one.second->id);
        lookLine = looks && (waitingForLook || (m_look != QLatin1String("auto") && !m_look.isEmpty()));
        const LookChoice *fitCard = looks && !noFootage ? chosenLookCard() : nullptr;
        if (fitCard && !fitCard->place.isEmpty()
            && m_fitFor == fitCard->place + QLatin1Char('#') + detectKey() + QLatin1Char('#') + m_kind && !m_fitVerdict.isEmpty())
            fit = QJsonObject{{"verdict", m_fitVerdict}, {"line", m_fitLine}, {"look_only", m_lookOnly && m_lookOnly->isChecked()}};
        if (noFootage && m_references)
            references = strings(m_references->files());
    }
    typed.insert("filmed_style", filmedStyleValue);
    typed.insert("fit", fit);
    typed.insert("multicam", multicam);
    typed.insert("auto_shown", shown);
    typed.insert("look_line", lookLine);
    typed.insert("theme", themeChoice(chosenLookCard()));
    typed.insert("references", references);
    return typed;
}

void NewVideoDialog::clearSentRequest()
{
    // sent: the next new video starts with a fresh note and "Let the AI decide"
    QSettings &memory = leSettings();
    memory.remove(QStringLiteral("firstCut/inputs"));
    m_inputsDraft = QJsonObject();
    memory.remove(QStringLiteral("firstCut/about"));
    memory.remove(QStringLiteral("firstCut/song"));
    memory.remove(QStringLiteral("firstCut/custom"));
    memory.remove(QStringLiteral("firstCut/noFootage"));
    memory.remove(QStringLiteral("firstCut/style"));
    memory.remove(QStringLiteral("firstCut/look"));
    for (const auto &key : {"theme", "captions", "music", "musicFile", "styleExplicit", "tab", "tabChosen", "tabFor", "freestyleByDefault"})
        memory.remove(QStringLiteral("firstCut/") + QLatin1String(key));
    memory.sync();
}

QString NewVideoDialog::normalizedLength() const
{
    const QString raw = m_length->text().trimmed().toLower();
    if (raw.isEmpty())
        return QString();
    const QRegularExpression clock(QStringLiteral("^(\\d+):(\\d{1,2})$"));
    auto match = clock.match(raw);
    double seconds = 0;
    if (match.hasMatch()) {
        seconds = match.captured(1).toInt() * 60 + match.captured(2).toInt();
        if (match.captured(2).toInt() >= 60)
            return QString();
    } else {
        const QRegularExpression units(QStringLiteral("^(\\d+(?:[.,]\\d+)?)\\s*(s|sec|secs|seconds?|m|min|mins|minutes?)$"));
        match = units.match(raw);
        if (!match.hasMatch())
            return QString();
        seconds = match.captured(1).replace(QLatin1Char(','), QLatin1Char('.')).toDouble()
                  * (match.captured(2).startsWith(QLatin1Char('s')) ? 1 : 60);
    }
    if (seconds <= 0 || seconds > 24 * 3600)
        return QString();
    return QStringLiteral("%1 seconds").arg(qRound(seconds));
}

bool NewVideoDialog::writeCustomStyle()
{
    if (!m_legacyStyle.isEmpty()) {
        const bool offered = std::any_of(m_catalog.cbegin(), m_catalog.cend(), [this](const StyleChoice &choice) {
            return choice.name == m_legacyStyle;
        });
        if (!offered) {
            m_problem->setText(tr("This saved Look is not available. Its saved choice is kept; copy its preferences to My Looks or choose another Look."));
            m_problem->show();
            return false;
        }
        m_style = m_legacyStyle;
        return true;
    }
    QJsonObject sliders;
    for (auto it = m_sliders.cbegin(); it != m_sliders.cend(); ++it)
        if (!m_aiSwitches.value(it.key())->isChecked())
            sliders.insert(it.key(), it.value()->value());
    if (sliders.isEmpty()) {
        m_style = QStringLiteral("none");
        return true;
    }
    const QString name = QStringLiteral("custom-%1").arg(QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd-hhmmsszzz")));
    QJsonObject spec{{QStringLiteral("name"), name}, {QStringLiteral("kind"), m_kind == QLatin1String("custom") || m_kind == QLatin1String("both") ? QStringLiteral("both") : m_kind},
                     {QStringLiteral("sliders"), sliders}};
    QTemporaryFile file;
    if (!file.open()) {
        m_problem->setText(tr("Couldn't prepare your Custom Look."));
        m_problem->show();
        return false;
    }
    file.write(QJsonDocument(spec).toJson());
    file.flush();
    const QString specPath = file.fileName();
    file.close();
    QByteArray output;
    const bool ok = leRun(aiChatSettings().value("python").toString(),
                          {aiRootPath(QStringLiteral("bridge/new_video_custom.py")), specPath},
                          nullptr, &output, 10000);
    const QJsonObject result = QJsonDocument::fromJson(output).object();
    if (!ok || !result.contains("id")) {
        m_problem->setText(tr("Couldn't save your Custom Look: %1").arg(result.value("error").toString(QString::fromUtf8(output))));
        m_problem->show();
        return false;
    }
    m_style = result.value("id").toString();
    m_customArtifacts[m_style] = {result.value("recipe").toString(), result.value("settings").toString()};
    return true;
}

} // namespace NewVideo
