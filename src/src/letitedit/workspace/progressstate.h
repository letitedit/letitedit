/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * One presentation rule for the home screen and the AI dock.
 */
#ifndef PROGRESSSTATE_H
#define PROGRESSSTATE_H

#include <QDateTime>
#include <QFile>
#include <QRegularExpression>
#include <QJsonObject>
#include <QJsonDocument>
#include <QList>
#include <QPair>
#include <QProcess>
#include <QString>
#include <QStringList>
#include <QUrl>

// The PC's progress folder (bridge/progress_feed.py root()) and one run's record in it (T193: runs/<run>.json).
inline QString progressDir()
{
    return qEnvironmentVariable("LETITEDIT_PROGRESS_DIR", qEnvironmentVariable("LOCALAPPDATA") + QStringLiteral("/letitedit/progress"));
}

inline QJsonObject progressReadJson(const QString &path)
{
    QFile file(path);
    return file.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(file.readAll()).object() : QJsonObject();
}

inline QJsonObject progressRecord(const QString &run)
{
    if (run.isEmpty())
        return {};
    QString safe = run;
    safe.replace(QRegularExpression(QStringLiteral("[^A-Za-z0-9_.-]")), QStringLiteral("_"));
    return progressReadJson(progressDir() + QStringLiteral("/runs/") + safe.left(120) + QStringLiteral(".json"));
}

// The run this window's chat is on: New video's chat names it (the same for every turn); any other request is its own.
inline QString progressRunOf(const QJsonObject &chat)
{
    const QString named = chat.value(QStringLiteral("progress_run")).toString();
    if (!named.isEmpty())
        return named;
    const int requestNumber = chat.value(QStringLiteral("request")).toInt();
    return requestNumber > 0 ? chat.value(QStringLiteral("chat_id")).toString() + QLatin1Char(':') + QString::number(requestNumber)
                             : QString();
}

inline const QStringList &progressSteps()
{
    static const QStringList steps{QStringLiteral("log"), QStringLiteral("story"), QStringLiteral("rough"), QStringLiteral("fine"),
                                   QStringLiteral("finish"), QStringLiteral("export"), QStringLiteral("review")};
    return steps;
}

// How long this has run: read from the record, nothing estimated.
inline QString progressSoFar(const QJsonObject &feed)
{
    const double started = feed.value(QStringLiteral("started")).toDouble();
    if (started <= 0)
        return {};
    const qint64 minutes = qMax<qint64>(0, QDateTime::currentSecsSinceEpoch() - qint64(started)) / 60;
    return minutes < 1 ? QStringLiteral("Under a minute so far")
           : minutes < 60 ? QStringLiteral("%1 min so far").arg(minutes)
                          : QStringLiteral("%1 h %2 min so far").arg(minutes / 60).arg(minutes % 60);
}

// What is happening now: the record's line, with the export's own percentage while it saves.
inline QString progressNow(const QJsonObject &feed)
{
    QString now = feed.value(QStringLiteral("now")).toString();
    const QString status = feed.value(QStringLiteral("export_status")).toString();
    if (feed.value(QStringLiteral("phase")).toString() == QLatin1String("export") && !status.isEmpty()) {
        const QJsonObject job = progressReadJson(status);
        const QString state = job.value(QStringLiteral("state")).toString();
        const int percent = qBound(0, int(job.value(QStringLiteral("progress")).toDouble() * 100), 100);
        const QString message = job.value(QStringLiteral("message")).toString();
        // The last steps of a save hold their percentage for a while (the mix is measured, the loudness finished, the
        // file checked): they say what they do instead of a bar that looks stuck (bridge render_queue's states).
        if (state == QLatin1String("checking"))
            now = message.startsWith(QLatin1String("Measuring the mix")) ? QStringLiteral("Checking the sound")
                                                                          : QStringLiteral("Checking the saved video");
        else if (state == QLatin1String("audio"))
            now = QStringLiteral("Finishing the sound");
        else if (state == QLatin1String("rendering") || state == QLatin1String("joining"))
            now = QStringLiteral("Saving your video: %1%").arg(percent);
        else if (state == QLatin1String("waiting") || state == QLatin1String("queued"))
            now = QStringLiteral("Saving your video: waiting for the PC to be free");
    }
    return now;
}

// A Review note's run (bridge/progress_feed.py is_note): a change to a video that exists, shown as the note and what's
// done, never as the first cut's seven steps (T221).
inline bool progressIsNote(const QJsonObject &feed)
{
    return feed.value(QStringLiteral("kind")).toString() == QLatin1String("review")
           || (feed.contains(QStringLiteral("whole_video")) && !feed.value(QStringLiteral("whole_video")).toBool());
}

// What a note's run has done so far, in its Undo labels' words.
inline QString progressDone(const QJsonObject &feed)
{
    QStringList done;
    for (const QJsonValue &value : feed.value(QStringLiteral("done")).toArray())
        if (!value.toString().trimmed().isEmpty())
            done << value.toString().trimmed();
    return done.isEmpty() ? QString() : QStringLiteral("Done: %1").arg(done.join(QStringLiteral("; ")));
}

inline QString progressFinishedText(const QJsonObject &feed)
{
    if (feed.value(QStringLiteral("active")).toBool()
        || feed.value(QStringLiteral("outcome")).toString() != QLatin1String("done"))
        return {};
    if (progressIsNote(feed))
        return {}; // the Review banner says what changed
    const QJsonObject review = feed.value(QStringLiteral("review")).toObject();
    const QString verdict = review.value(QStringLiteral("verdict")).toString();
    QString label = verdict == QLatin1String("ready") ? QStringLiteral("Your video is ready")
                    : verdict == QLatin1String("revise") ? QStringLiteral("First cut done: the review found changes to make")
                    : verdict == QLatin1String("blocked") ? QStringLiteral("First cut blocked: the review found a serious issue")
                                                         : QStringLiteral("First cut done: review not finished");
    const QString report = review.value(QStringLiteral("report")).toString();
    if (!report.isEmpty() && QFile::exists(report))
        label += QStringLiteral(" &mdash; <a href=\"%1\">Read the review</a>")
                     .arg(QUrl::fromLocalFile(report).toString().toHtmlEscaped());
    return label;
}

struct ProgressState {
    bool visible = false;
    bool limit = false;  // waiting for the AI's usage limit to reset
    QString label;       // the phase ("Polishing the cuts", "Fixing what the check found (round 2)") or what it waits for
    QString now;         // what is happening now
    QString soFar;       // time so far, read from the record
    int step = 0;        // 0..6 of progressSteps(); never goes back for a run
    QString stage;
    bool note = false;   // a Review note: no steps on show, what's done instead (T221)
    QString done;        // "Done: softer light on the faces"
};

// startingVideo: this window has just asked for a whole video and its record may not have caught up yet. A small
// request in the chat, or a tool call from anyone else, is not a video being made: it never shows the card.
inline ProgressState progressState(const QJsonObject &feed, const QJsonObject &chat, bool startingVideo = false)
{
    const bool busy = chat.value(QStringLiteral("busy")).toBool();
    const QString run = progressRunOf(chat);
    const bool mine = busy && !run.isEmpty() && feed.value(QStringLiteral("run")).toString() == run
                      && feed.value(QStringLiteral("active")).toBool();
    ProgressState result;
    result.visible = mine || (busy && startingVideo);
    if (!result.visible)
        return result;
    if (mine) {
        result.label = feed.value(QStringLiteral("label")).toString();
        result.now = progressNow(feed);
        result.stage = feed.value(QStringLiteral("stage")).toString();
        result.step = qMax(0, progressSteps().indexOf(result.stage));
        result.soFar = progressSoFar(feed);
        result.note = progressIsNote(feed);
        if (result.note)
            result.done = progressDone(feed);
    }
    if (result.label.isEmpty())
        result.label = QStringLiteral("Getting ready...");
    const QJsonObject limit = chat.value(QStringLiteral("new_video_limit")).toObject();
    if (!limit.value(QStringLiteral("words")).toString().isEmpty()) {
        result.limit = true;
        result.label = limit.value(QStringLiteral("words")).toString();
        result.now.clear();
    } else if (chat.value(QStringLiteral("waiting")).toBool()) {
        result.label = QStringLiteral("Waiting for you: answer the question in the AI panel");
        result.now.clear();
    }
    return result;
}

inline void syncProgressWaiting(const QJsonObject &feed, const QJsonObject &chat,
                                const QString &python, const QString &script)
{
    if (!chat.value(QStringLiteral("busy")).toBool())
        return;
    const QString run = progressRunOf(chat);
    if (run.isEmpty() || feed.value(QStringLiteral("run")).toString() != run || !feed.value(QStringLiteral("active")).toBool())
        return;
    const bool waiting = chat.value(QStringLiteral("waiting")).toBool();
    if ((feed.value(QStringLiteral("state")).toString() == QLatin1String("waiting")) == waiting)
        return;
    static QString lastRun;
    static bool lastWaiting = false;
    static qint64 lastAttempt = 0;
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    if (lastRun == run && lastWaiting == waiting && now - lastAttempt < 1500)
        return;
    lastRun = run;
    lastWaiting = waiting;
    lastAttempt = now;
    const QJsonObject meta{{QStringLiteral("run"), run}};
    QProcess::startDetached(python, {script, waiting ? QStringLiteral("waiting") : QStringLiteral("working"),
                                     QStringLiteral("--json"),
                                     QString::fromUtf8(QJsonDocument(meta).toJson(QJsonDocument::Compact))});
}

#endif // PROGRESSSTATE_H
