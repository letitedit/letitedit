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

// New video: what the chosen Look asks for up front (its boxes), and the record kept beside the video.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// ---- what the chosen Look asks for up front (T64): one screen of boxes -------------------------------------------
QString NewVideoDialog::needWords(const QString &need)
{
    return need == QLatin1String("required")      ? tr("Required")
           : need == QLatin1String("recommended") ? tr("Strongly recommended")
                                                  : tr("Optional");
}

// what each role means to the AI, in the request
QString NewVideoDialog::roleMeaning(const QString &role)
{
    if (role == QLatin1String("show"))
        return QStringLiteral("these may appear on screen in the video");
    if (role == QLatin1String("style"))
        return QStringLiteral("look at these for the feel the person wants; they must never appear in the video");
    if (role == QLatin1String("voiceover"))
        return QStringLiteral("the person's own voice: use it as the narration");
    if (role == QLatin1String("product"))
        return QStringLiteral("what the video is selling or showing");
    if (role == QLatin1String("person"))
        return QStringLiteral("who the video is about or for");
    if (role == QLatin1String("about"))
        return QStringLiteral("what the video is about, in the person's words");
    return QString();
}

QString NewVideoDialog::mediaKind(const QString &path)
{
    const QString ext = QFileInfo(path).suffix().toLower();
    static const QStringList video{"mp4", "mov", "m4v", "mkv", "avi", "mts", "webm", "mxf"};
    static const QStringList audio{"wav", "mp3", "m4a", "flac", "aac", "ogg"};
    static const QStringList photo{"jpg", "jpeg", "png", "heic", "webp", "bmp"};
    return video.contains(ext) ? QStringLiteral("video")
           : audio.contains(ext) ? QStringLiteral("audio")
           : photo.contains(ext) ? QStringLiteral("photo")
                                 : QStringLiteral("other");
}

bool NewVideoDialog::askEmpty(const QString &id) const
{
    if (auto t = m_askText.value(id))
        return t->toPlainText().trimmed().isEmpty();
    if (auto f = m_askFiles.value(id))
        return f->count() == 0;
    return true;
}

// the chosen Look when it has boxes (not "Let the AI pick"), else null
const LookChoice *NewVideoDialog::askingLook() const
{
    const LookStyle *ls = lookStyle(m_style);
    const LookChoice *look = ls ? findLook(*ls, m_look) : nullptr;
    return look && !look->asks.isEmpty() ? look : nullptr;
}

// "Still needed: ..." for the required boxes that are empty, else nothing
QString NewVideoDialog::missingInputsLine() const
{
    QStringList missing;
    for (const QString &id : m_askOrder)
        if (m_askDefs.value(id).need == QLatin1String("required") && askEmpty(id))
            missing << m_askDefs.value(id).label;
    if (missing.isEmpty())
        return QString();
    const QString list = missing.join(QStringLiteral(", "));
    return list.endsWith(QLatin1Char('?')) ? tr("Still needed: %1").arg(list) : tr("Still needed: %1.").arg(list);
}

void NewVideoDialog::captureInputsDraft()
{
    if (m_inputsLookId.isEmpty())
        return;
    QJsonObject d;
    for (const QString &id : m_askOrder) {
        if (auto t = m_askText.value(id))
            d.insert(id, t->toPlainText());
        else if (auto f = m_askFiles.value(id))
            d.insert(id, QJsonArray::fromStringList(f->files()));
    }
    m_inputsDraft.insert(m_inputsLookId, d);
}

void NewVideoDialog::updateInputsState()
{
    for (const QString &id : m_askOrder) {
        auto status = m_askStatus.value(id);
        if (!status)
            continue;
        const LookAsk &ask = m_askDefs.value(id);
        QString line;
        if (askEmpty(id)) {
            if (ask.need == QLatin1String("recommended"))
                line = ask.instead.isEmpty() ? tr("Without this, your AI works with what it has.")
                                             : tr("If you leave this empty: %1").arg(ask.instead);
        }
        status->setText(line);
        status->setVisible(!line.isEmpty());
    }
    const QString missing = missingInputsLine();
    const bool ready = m_pages->currentIndex() == PGo;
    m_inputsNote->setText(missing);
    m_inputsNote->setVisible(ready && !missing.isEmpty());
    if (ready)
        m_go->setEnabled(missing.isEmpty());
    captureInputsDraft();
}

// the files boxes can send a tile to the next one
void NewVideoDialog::refreshMoveTargets()
{
    QStringList boxes;
    for (const QString &id : m_askOrder)
        if (m_askDefs.value(id).kind == QLatin1String("files"))
            boxes << id;
    for (int i = 0; i < boxes.size(); ++i) {
        AskFiles *from = m_askFiles.value(boxes[i]);
        const QString to = boxes[(i + 1) % boxes.size()];
        if (from)
            from->setCanMove(boxes.size() > 1, m_askDefs.value(to).label);
    }
}

void NewVideoDialog::moveTile(AskFiles *from, const QString &path)
{
    QStringList boxes;
    for (const QString &id : m_askOrder)
        if (m_askDefs.value(id).kind == QLatin1String("files"))
            boxes << id;
    const int at = boxes.indexOf(from->askId());
    if (at < 0 || boxes.size() < 2)
        return;
    if (AskFiles *to = m_askFiles.value(boxes[(at + 1) % boxes.size()])) {
        from->removeFile(path);
        to->addFiles({path});
    }
}

void NewVideoDialog::applyFacts(const QString &path)
{
    const auto facts = m_askFacts.value(path);
    QPixmap picture;
    if (!facts.second.isEmpty())
        picture = QPixmap(facts.second);
    for (auto box : std::as_const(m_askFiles))
        box->setFacts(path, facts.first, picture);
}

// length and a small picture for new tiles, from the same tool side as the media list. Each file is named at once
// and its details follow, so a file that is slow to open (Google Drive, not yet downloaded) holds nothing up.
void NewVideoDialog::requestFacts(const QStringList &paths)
{
    QStringList ask;
    for (const QString &path : paths) {
        if (m_askFacts.contains(path))
            applyFacts(path);
        else {
            m_askFacts.insert(path, {QString(), QString()});
            ask << path;
        }
    }
    if (ask.isEmpty())
        return;
    auto process = new QProcess(this);
    auto buffer = std::make_shared<QByteArray>();
    connect(process, &QProcess::readyReadStandardOutput, this, [this, process, buffer]() {
        *buffer += process->readAllStandardOutput();
        int newline;
        while ((newline = buffer->indexOf('\n')) >= 0) {
            const QJsonObject item = QJsonDocument::fromJson(buffer->left(newline)).object();
            buffer->remove(0, newline + 1);
            if (item.contains("length")) {
                const QJsonObject l = item.value("length").toObject();
                const int seconds = qRound(l.value("duration_s").toDouble());
                const QString path = l.value("path").toString();
                m_askFacts[path].first = QStringLiteral("%1:%2").arg(seconds / 60).arg(seconds % 60, 2, 10, QLatin1Char('0'));
                applyFacts(path);
            } else if (item.contains("thumbnail")) {
                const QJsonObject t = item.value("thumbnail").toObject();
                const QString path = t.value("path").toString();
                m_askFacts[path].second = t.value("image").toString();
                applyFacts(path);
            } else if (item.contains("missing")) {
                const QString path = item.value("missing").toString();
                m_askFacts[path].first = tr("can't open");
                applyFacts(path);
            }
        }
    });
    connect(process, &QProcess::finished, process, &QObject::deleteLater);
    QStringList args{aiRootPath(QStringLiteral("bridge/look_inputs.py")), QStringLiteral("facts"),
                     aiRootPath(QStringLiteral("app/ffprobe.exe")),
                     leSettings().fileName() + QStringLiteral(".media-cache.json")};
    args << ask;
    process->start(aiChatSettings().value("python").toString(), args);
}

// The boxes for this Look on Ready. What was typed for another Look is kept: a box asking for the same thing takes it
// along, and a line says plainly what no longer applies.
void NewVideoDialog::showInputsFor(const LookChoice *look)
{
    const QString wanted = look ? look->id : QString();
    if (wanted == m_inputsLookId)
        return;
    captureInputsDraft();
    const QJsonObject oldDraft = m_inputsDraft.value(m_inputsLookId).toObject();
    const QString oldName = m_inputsLookLabel;
    QMap<QString, QJsonValue> given; // role|kind -> what is in that box
    QMap<QString, QString> givenLabels;
    for (const QString &id : m_askOrder)
        if (!askEmpty(id)) {
            const LookAsk &ask = m_askDefs.value(id);
            const QString key = ask.role + QLatin1Char('|') + ask.kind;
            given.insert(key, oldDraft.value(id));
            givenLabels.insert(key, ask.label);
        }
    if (look) {
        QJsonObject draft = m_inputsDraft.value(look->id).toObject();
        for (const LookAsk &ask : look->asks) {
            const QString key = ask.role + QLatin1Char('|') + ask.kind;
            if (!given.contains(key))
                continue;
            const QJsonValue have = draft.value(ask.id);
            if (have.isUndefined() || have.toString().isEmpty() && have.toArray().isEmpty())
                draft.insert(ask.id, given.value(key));
            givenLabels.remove(key);
        }
        m_inputsDraft.insert(look->id, draft);
        fillInputs(*look);
    } else {
        clearInputs();
    }
    const QStringList gone = givenLabels.values();
    m_inputsGone->setText(gone.isEmpty() ? QString()
                                         : tr("From %1, this no longer applies: %2. It's kept if you change back.")
                                               .arg(oldName, gone.join(QStringLiteral(", "))));
    m_inputsGone->setVisible(!gone.isEmpty());
}

void NewVideoDialog::clearInputs()
{
    m_askOrder.clear();
    m_askDefs.clear();
    m_askText.clear();
    m_askFiles.clear();
    m_askStatus.clear();
    clearLayout(m_inputsColumn);
    m_inputsLookId.clear();
    m_inputsLookLabel.clear();
}

// One box a Look asks for: its name and how much it's needed, a line of help, then a place to type or drop files
QFrame *NewVideoDialog::inputBox(const LookAsk &ask, const QJsonObject &draft)
{
    auto box = new QFrame(m_inputsHolder);
    box->setObjectName(QStringLiteral("newVideoAsk_%1").arg(ask.id));
    auto column = new QVBoxLayout(box);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(4);
    auto head = new QHBoxLayout;
    head->setSpacing(8);
    auto title = new QLabel(ask.label, box);
    title->setObjectName(QStringLiteral("newVideoAskTitle_%1").arg(ask.id));
    title->setStyleSheet(QStringLiteral("font-size: 13px; font-weight: 700;"));
    QFont titleFont = title->font();
    titleFont.setPixelSize(13);
    titleFont.setBold(true);
    if (QFontMetrics(titleFont).horizontalAdvance(ask.label) > 300) {
        title->setWordWrap(true);
        title->setMinimumWidth(240);
    }
    head->addWidget(title);
    auto badge = new QLabel(needWords(ask.need), box);
    badge->setObjectName(QStringLiteral("newVideoAskBadge_%1").arg(ask.id));
    badge->setStyleSheet(QStringLiteral("font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 8px; "
                                        "color: %1; background: %2;")
                             .arg(QString::fromLatin1(LetItEditColors::cream),
                                  ask.need == QLatin1String("required")      ? QStringLiteral("#A04E2C")
                                  : ask.need == QLatin1String("recommended") ? QString::fromLatin1(LetItEditColors::tealDeep)
                                                                             : QStringLiteral("#3B454B")));
    head->addWidget(badge, 0, Qt::AlignVCenter);
    head->addStretch(1);
    column->addLayout(head);
    if (!ask.hint.isEmpty()) {
        auto hint = new QLabel(ask.hint, box);
        hint->setObjectName(QStringLiteral("newVideoAskHint_%1").arg(ask.id));
        hint->setWordWrap(true);
        hint->setProperty("studioMuted", true);
        column->addWidget(hint);
    }
    if (ask.kind == QLatin1String("text")) {
        auto text = new QPlainTextEdit(box);
        text->setObjectName(QStringLiteral("newVideoAskText_%1").arg(ask.id));
        text->setAccessibleName(ask.label);
        text->setFixedHeight(62);
        text->setPlainText(draft.value(ask.id).toString());
        connect(text, &QPlainTextEdit::textChanged, this, [this]() { updateInputsState(); });
        m_askText.insert(ask.id, text);
        column->addWidget(text);
    } else {
        const bool audio = ask.kind == QLatin1String("audio");
        auto files = new AskFiles(ask.id, audio, box);
        files->setAccessibleName(ask.label);
        files->onChanged([this]() { updateInputsState(); });
        files->onAdded([this](const QStringList &added) { requestFacts(added); });
        files->onMove([this](AskFiles *from, const QString &path) { moveTile(from, path); });
        m_askFiles.insert(ask.id, files);
        column->addWidget(files);
        auto add = new QPushButton(audio ? tr("Add a file...") : tr("Add files..."), box);
        add->setObjectName(QStringLiteral("newVideoAskAdd_%1").arg(ask.id));
        add->setAutoDefault(false);
        connect(add, &QPushButton::clicked, this, [this, files, audio]() {
            const QString start = m_folder->text().trimmed().isEmpty() ? Settings.openPath() : m_folder->text().trimmed();
            const QString filter = audio ? tr("Sound (*.wav *.mp3 *.m4a *.flac *.aac *.ogg);;All files (*)")
                                         : tr("Pictures, video and sound (*.jpg *.jpeg *.png *.heic *.webp *.bmp *.mp4 *.mov *.m4v *.mkv *.avi *.mts *.webm *.mxf *.wav *.mp3 *.m4a *.flac *.aac *.ogg *.pdf);;All files (*)");
            const QStringList picked = audio ? QStringList{QFileDialog::getOpenFileName(this, tr("Choose a sound file"), start, filter)}
                                             : QFileDialog::getOpenFileNames(this, tr("Choose files"), start, filter);
            QStringList clean;
            for (const QString &p : picked)
                if (!p.isEmpty())
                    clean << QDir::toNativeSeparators(p);
            files->addFiles(clean);
        });
        head->addWidget(add);
        // for tests and screen readers: paths set here (semicolon separated) are added, as if dropped
        auto paste = new QLineEdit(box);
        paste->setObjectName(QStringLiteral("newVideoAskPaste_%1").arg(ask.id));
        paste->setFixedSize(1, 1);
        paste->setStyleSheet(QStringLiteral("color: transparent; background: transparent; border: none;"));
        connect(paste, &QLineEdit::textChanged, this, [files, paste](const QString &text) {
            if (text.isEmpty())
                return;
            files->addFiles(text.split(QLatin1Char(';'), Qt::SkipEmptyParts));
            paste->clear();
        });
        head->addWidget(paste);
    }
    auto status = new QLabel(box);
    status->setObjectName(QStringLiteral("newVideoAskStatus_%1").arg(ask.id));
    status->setWordWrap(true);
    status->setProperty("studioMuted", true);
    m_askStatus.insert(ask.id, status);
    column->addWidget(status);
    return box;
}

void NewVideoDialog::fillInputs(const LookChoice &look)
{
    captureInputsDraft();
    clearInputs();
    m_inputsLookId = look.id;
    m_inputsLookLabel = look.label;
    const QJsonObject draft = m_inputsDraft.value(look.id).toObject();
    for (const LookAsk &ask : look.asks) {
        m_askOrder << ask.id;
        m_askDefs.insert(ask.id, ask);
    }
    // optional files take half the width, side by side, so the whole Look fits on one screen
    QHBoxLayout *pair = nullptr;
    for (const LookAsk &ask : look.asks) {
        const bool half = ask.need == QLatin1String("optional") && ask.kind != QLatin1String("text");
        QFrame *box = inputBox(ask, draft);
        if (!half) {
            pair = nullptr;
            m_inputsColumn->addWidget(box);
        } else if (pair) {
            pair->addWidget(box, 1);
            pair = nullptr;
        } else {
            pair = new QHBoxLayout;
            pair->setSpacing(18);
            pair->addWidget(box, 1);
            m_inputsColumn->addLayout(pair);
        }
    }
    refreshMoveTargets();
    for (const QString &id : m_askOrder)
        if (auto files = m_askFiles.value(id))
            files->addFiles(draft.value(id).toVariant().toStringList());
    updateInputsState();
}

// The answers as the record kept beside the video (bridge\look_inputs.py reads it)
QJsonObject NewVideoDialog::inputsRecord(const LookChoice &look) const
{
    QJsonArray boxes;
    for (const QString &id : m_askOrder) {
        const LookAsk &ask = m_askDefs.value(id);
        QJsonObject box{{"id", ask.id}, {"kind", ask.kind}, {"role", ask.role}, {"label", ask.label}, {"need", ask.need}};
        if (auto t = m_askText.value(id)) {
            box.insert("text", t->toPlainText().trimmed());
        } else if (auto f = m_askFiles.value(id)) {
            QJsonArray files;
            for (const QString &path : f->files()) {
                QJsonObject entry{{"path", path}, {"name", QFileInfo(path).fileName()}, {"kind", mediaKind(path)}};
                const QString length = m_askFacts.value(path).first;
                if (!length.isEmpty())
                    entry.insert("length", length);
                files.append(entry);
            }
            box.insert("files", files);
        }
        boxes.append(box);
    }
    return QJsonObject{{"format", "letitedit-inputs/1"},
                       {"look", look.id},
                       {"look_label", look.label},
                       {"created", QDateTime::currentDateTimeUtc().toString(Qt::ISODate)},
                       {"inputs", boxes}};
}

// The request's words for the answers, by role; no question follows the Go button
QString NewVideoDialog::inputsRequestText(const QJsonObject &record, const QString &recordPath) const
{
    QString t = QStringLiteral("What the person gave this Look up front (kept in %1). Once the project exists, keep it "
                               "beside the video with letitedit_looks(action: \"inputs\", project: <the project .mlt>, inputs: \"%1\"); in "
                               "later rounds read it back with letitedit_looks(action: \"inputs\", project: ..., inputs: \"read\"):\n")
                    .arg(QDir::toNativeSeparators(recordPath));
    QStringList empties;
    QSet<QString> roles;
    for (const auto &bv : record.value("inputs").toArray()) {
        const QJsonObject box = bv.toObject();
        const QString role = box.value("role").toString();
        roles.insert(role);
        QString given;
        if (box.value("kind").toString() == QLatin1String("text")) {
            given = box.value("text").toString();
        } else {
            QStringList paths;
            for (const auto &fv : box.value("files").toArray())
                paths << fv.toObject().value("path").toString();
            given = paths.join(QStringLiteral("; "));
        }
        t += QStringLiteral("- %1 (\"%2\"): %3\n")
                 .arg(role, box.value("label").toString(), given.isEmpty() ? QStringLiteral("not given") : given);
        if (given.isEmpty()) {
            const LookAsk ask = m_askDefs.value(box.value("id").toString());
            empties << (ask.instead.isEmpty() ? QStringLiteral("%1: not given, so work without it").arg(role)
                                              : QStringLiteral("%1: %2").arg(role, ask.instead));
        }
    }
    QStringList meanings;
    for (const QString &role : roles)
        if (!roleMeaning(role).isEmpty())
            meanings << QStringLiteral("%1 = %2").arg(role, roleMeaning(role));
    if (!meanings.isEmpty())
        t += QStringLiteral("Roles: %1.\n").arg(meanings.join(QStringLiteral("; ")));
    if (!empties.isEmpty())
        t += QStringLiteral("Left empty: %1.\n").arg(empties.join(QStringLiteral("; ")));
    t += QStringLiteral("Nothing more will be asked of the person after they press Go: do not ask them anything about "
                        "these, or for approval of a script, a beat table or an asset; decide for yourself. The files "
                        "are theirs and are only read, never changed or moved. If you leave a \"show\" file out of "
                        "the video, record why with letitedit_looks(action: \"inputs\", project: ..., unused: {<file path>: <reason>}).\n");
    return t;
}

QString NewVideoDialog::writeInputsRecord(const QJsonObject &record) const
{
    const QString dir = QDir(QFileInfo(leSettings().fileName()).absolutePath()).filePath(QStringLiteral("new-video-inputs"));
    if (!QDir().mkpath(dir))
        return QString();
    const QString path = QDir(dir).filePath(
        QStringLiteral("inputs-%1.json").arg(QDateTime::currentDateTimeUtc().toString(QStringLiteral("yyyyMMdd-hhmmsszzz"))));
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        return QString();
    file.write(QJsonDocument(record).toJson());
    return path;
}

// Keep the record beside the video as soon as the video opens in this window (the AI also attaches it with
// letitedit_looks; whichever comes first wins and the other leaves it as it is).
void NewVideoDialog::keepInputsBesideProject(const QString &recordPath)
{
    // one request is waiting for its video at a time: a newer request takes over from an older one, so a video never
    // gets the record of an earlier request
    static QPointer<QTimer> waiting;
    if (waiting)
        waiting->deleteLater();
    const QString fromFile = m_window->fileName();
    auto timer = new QTimer(m_window);
    waiting = timer;
    timer->setInterval(1500);
    const QDateTime sentAt = QDateTime::currentDateTime();
    connect(timer, &QTimer::timeout, m_window, [window = m_window, timer, sentAt, fromFile, recordPath]() {
        if (sentAt.secsTo(QDateTime::currentDateTime()) > 6 * 3600) {
            timer->deleteLater();
            return;
        }
        const QString project = window->fileName();
        if (project.isEmpty() || project == fromFile || !QFileInfo(project).isFile())
            return;
        const QDateTime born = QFileInfo(project).birthTime();
        if (born.isValid() && born.addSecs(5) < sentAt)
            return; // a video that was already there, not the one this request is making
        const QString target = QDir(leSideFolder(project)).filePath(QStringLiteral("inputs.json"));
        if (!QFileInfo::exists(target) && QDir().mkpath(QFileInfo(target).absolutePath()))
            QFile::copy(recordPath, target);
        if (QFileInfo::exists(target))
            timer->deleteLater();
    });
    timer->start();
}

} // namespace NewVideo
