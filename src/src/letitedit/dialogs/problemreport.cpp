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

#include "letitedit/dialogs/problemreport.h"

#include "Logger.h"
#include "gpuinfo.h"
#include "letitedit/airoot.h"
#include "letitedit/chat/aichatpanel.h"
#include "settings.h"

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QQuickWindow>
#include <QRandomGenerator>
#include <QRegularExpression>
#include <QSysInfo>
#include <QtWidgets>

#include <algorithm>
#include <functional>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace ProblemReport {

// The reports server (T368; deployed 24 Nov 2026 with the owner's yes). Only the person's own window (instance "main")
// uses it; test windows send nowhere unless LETITEDIT_REPORTS_URL names a stand-in.
static const char kReportsUrl[] = "https://reports.letitedit.app";
static const char kTeamEmail[] = "teamletitedit@gmail.com";
static const char kFormat[] = "letitedit-problem-report/1";
static constexpr int kMaxWords = 5000;
static constexpr int kLogLines = 200;
static constexpr int kLogBytes = 48 * 1024;
static constexpr int kMaxReportBytes = 128 * 1024;
static constexpr int kCrashNoteDays = 14;

static QString appData()
{
    return QDir::fromNativeSeparators(Settings.appDataLocation());
}

static QString crashDir(const QString &base = QString())
{
    return (base.isEmpty() ? appData() : QDir::fromNativeSeparators(base)) + QStringLiteral("/crash");
}

static QString setupDir()
{
    const QString named = qEnvironmentVariable("LETITEDIT_SETUP_DIR");
    return named.isEmpty() ? aiRootPath(QStringLiteral("setup")) : QDir::fromNativeSeparators(named);
}

static QString randomHex()
{
    QString out;
    for (int i = 0; i < 4; ++i)
        out += QStringLiteral("%1").arg(QRandomGenerator::system()->generate(), 8, 16, QLatin1Char('0'));
    return out;
}

static QJsonObject readJson(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return QJsonObject();
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data = data.mid(3);
    return QJsonDocument::fromJson(data).object();
}

static bool writeJson(const QString &path, const QJsonValue &value)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly))
        return false;
    file.write(value.isArray() ? QJsonDocument(value.toArray()).toJson() : QJsonDocument(value.toObject()).toJson());
    return file.commit();
}

QString buildName()
{
    const QString name = QFileInfo(QCoreApplication::applicationFilePath()).completeBaseName();
    static const QRegularExpression stamp(QStringLiteral("^letitedit-(\\d{8}\\.\\d+)$"));
    const auto match = stamp.match(name);
    return match.hasMatch() ? match.captured(1) : name;
}

// ---- the cleaning --------------------------------------------------------------------------------------------------

static QStringList namesFrom(const QStringList &candidates)
{
    QStringList names;
    for (const QString &candidate : candidates) {
        const QString name = candidate.trimmed();
        if (name.size() >= 3 && !names.contains(name, Qt::CaseInsensitive))
            names << name;
    }
    // longer first, so a name inside another is replaced after it
    std::sort(names.begin(), names.end(), [](const QString &a, const QString &b) { return a.size() > b.size(); });
    return names;
}

static QString replaceNames(QString text, const QStringList &names, const QString &with)
{
    for (const QString &name : names) {
        const QRegularExpression word(QStringLiteral("(?<![A-Za-z0-9<])") + QRegularExpression::escape(name)
                                          + QStringLiteral("(?![A-Za-z0-9>])"),
                                      QRegularExpression::CaseInsensitiveOption);
        text.replace(word, with);
    }
    return text;
}

static QString withExtension(const QString &placeholder, const QString &matched)
{
    static const QRegularExpression ext(QStringLiteral("\\.([A-Za-z0-9]{1,5})$"));
    const auto m = ext.match(matched);
    return m.hasMatch() ? placeholder + QLatin1Char('.') + m.captured(1).toLower() : placeholder;
}

static QString replaceEach(const QString &text, const QRegularExpression &pattern,
                           const std::function<QString(const QRegularExpressionMatch &)> &with)
{
    QString out;
    qsizetype at = 0;
    auto it = pattern.globalMatch(text);
    while (it.hasNext()) {
        const auto m = it.next();
        out += text.mid(at, m.capturedStart() - at);
        out += with(m);
        at = m.capturedEnd();
    }
    out += text.mid(at);
    return out;
}

QString clean(const QString &input)
{
    static const QString media = QStringLiteral(
        "mp4|mov|m4v|mkv|avi|webm|mts|m2ts|mxf|wmv|flv|3gp|mpg|mpeg|braw|r3d|insv|lrv|wav|mp3|m4a|aac|flac|ogg|opus|"
        "aif|aiff|wma|png|jpg|jpeg|heic|heif|gif|webp|bmp|tif|tiff|psd|svg|mlt|srt|vtt|ass|cube|kdenlive|prproj|drp");
    static const QRegularExpression jwt(QStringLiteral("eyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{4,}"));
    static const QRegularExpression skKey(QStringLiteral("(?<![A-Za-z0-9])sk-(?:ant-)?[A-Za-z0-9_-]{16,}"));
    static const QRegularExpression bearer(QStringLiteral("\\b(bearer|basic)\\s+(?!<secret>)[A-Za-z0-9._~+/=-]{8,}"),
                                           QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression keyValue(
        QStringLiteral("\\b(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|token|secret|"
                       "client[_-]?secret|password|passwd|pwd|authorization|cookie|session[_-]?(?:key|token|id))"
                       "(\"?\\s*[:=]\\s*\"?)(?!<secret>)[^\\s\"',;&]+"),
        QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression url(
        QStringLiteral("\\b((?:https?|wss?|ftp)://)(?:[^\\s/@\"'<>]+@)?([^\\s/?#\"'<>]+)([^\\s\"'<>]*)"),
        QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression fileUrl(QStringLiteral("\\bfile:/{1,3}[^\\s\"'<>]+"),
                                            QRegularExpression::CaseInsensitiveOption);
    // An absolute path: a drive, a network share or a /c/... or /Users/... start, folders (which may hold spaces, each
    // followed by a separator), then a file name with an extension (spaces allowed) or a word.
    static const QRegularExpression path(QStringLiteral(
        "(?:(?<![A-Za-z0-9])[A-Za-z]:|\\\\\\\\[^\\\\/\\s\"'<>|]+|(?<![\\w.~-])(?=/(?:Users|home|mnt|tmp|var|private|"
        "Volumes|[a-zA-Z])/))(?:[\\\\/][^\\\\/\\n\"'<>|*?]*(?=[\\\\/]))*[\\\\/](?:[^\\\\/\\n\"'<>|*?]*?\\.[A-Za-z0-9]{1,5}"
        "(?![A-Za-z0-9])|[^\\s\\\\/\"'<>|*?]*)"));
    static const QRegularExpression quotedFile(QStringLiteral("([\"'])[^\"'\\n<>]{0,200}?\\.(%1)\\1").arg(media),
                                               QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression bareFile(
        QStringLiteral("(?<![\\w.<>-])[\\w()&+'-][\\w.()&+'-]*\\.(%1)(?![A-Za-z0-9])").arg(media),
        QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression email(
        QStringLiteral("[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}"));
    static const QRegularExpression longHex(QStringLiteral("(?<![A-Za-z0-9])[A-Fa-f0-9]{32,}(?![A-Za-z0-9])"));
    static const QRegularExpression longRun(QStringLiteral(
        "(?<![A-Za-z0-9+/=_-])(?=[A-Za-z0-9+/_-]*[0-9])(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{40,}={0,2}"));
    static const QStringList users = namesFrom({qEnvironmentVariable("USERNAME"), QDir(QDir::homePath()).dirName()});
    static const QStringList pcs = namesFrom({qEnvironmentVariable("COMPUTERNAME"),
                                              qEnvironmentVariable("USERDOMAIN").compare(QStringLiteral("WORKGROUP"), Qt::CaseInsensitive)
                                                  ? qEnvironmentVariable("USERDOMAIN")
                                                  : QString()});

    QString text = input;
    text.replace(jwt, QStringLiteral("<secret>"));
    text.replace(skKey, QStringLiteral("<secret>"));
    text.replace(bearer, QStringLiteral("\\1 <secret>"));
    text.replace(keyValue, QStringLiteral("\\1\\2<secret>"));
    text = replaceEach(text, url, [](const QRegularExpressionMatch &m) {
        const QString rest = m.captured(3);
        return m.captured(1) + m.captured(2) + (rest.isEmpty() || rest == QLatin1String("/") ? rest : QStringLiteral("/..."));
    });
    text = replaceEach(text, fileUrl, [](const QRegularExpressionMatch &m) {
        return withExtension(QStringLiteral("<path>"), m.captured(0));
    });
    text = replaceEach(text, path, [](const QRegularExpressionMatch &m) {
        return withExtension(QStringLiteral("<path>"), m.captured(0).trimmed());
    });
    text = replaceEach(text, quotedFile, [](const QRegularExpressionMatch &m) {
        return m.captured(1) + QStringLiteral("<file>.") + m.captured(2).toLower() + m.captured(1);
    });
    text = replaceEach(text, bareFile, [](const QRegularExpressionMatch &m) {
        return QStringLiteral("<file>.") + m.captured(1).toLower();
    });
    text.replace(email, QStringLiteral("<email>"));
    text = replaceNames(text, users, QStringLiteral("<user>"));
    text = replaceNames(text, pcs, QStringLiteral("<pc>"));
    text.replace(longHex, QStringLiteral("<secret>"));
    text.replace(longRun, QStringLiteral("<secret>"));
    return text;
}

// ---- the parts -----------------------------------------------------------------------------------------------------

// The last lines of a text file (at most 256 KB read from its end), each at most 500 characters; a run of lines that
// differ only in their numbers is kept as its first line and a count.
static QString tailOf(const QString &file, int maxLines)
{
    QFile f(file);
    if (!f.open(QIODevice::ReadOnly))
        return QString();
    constexpr qint64 window = 256 * 1024;
    const qint64 size = f.size();
    if (size > window)
        f.seek(size - window);
    QByteArray data = f.read(window);
    if (size > window) {
        const int nl = data.indexOf('\n');
        if (nl >= 0)
            data = data.mid(nl + 1);
    }
    static const QRegularExpression digits(QStringLiteral("\\d+"));
    QStringList lines;
    QString lastKey;
    int repeats = 0;
    auto flush = [&]() {
        if (repeats > 0)
            lines << QStringLiteral("(%1 more lines like the one above)").arg(repeats);
        repeats = 0;
    };
    for (QString line : QString::fromUtf8(data).split(QLatin1Char('\n'))) {
        line.remove(QLatin1Char('\r'));
        if (line.trimmed().isEmpty())
            continue;
        if (line.size() > 500)
            line = line.left(500) + QStringLiteral("...");
        QString key = line;
        key.replace(digits, QStringLiteral("#"));
        if (key == lastKey) {
            ++repeats;
            continue;
        }
        flush();
        lastKey = key;
        lines << line;
    }
    flush();
    return lines.mid(qMax(0, int(lines.size()) - maxLines)).join(QLatin1Char('\n'));
}

static QString capFront(QString text, int bytes)
{
    while (text.toUtf8().size() > bytes) {
        const int nl = text.indexOf(QLatin1Char('\n'));
        text = nl < 0 ? text.right(bytes / 2) : text.mid(nl + 1);
    }
    return text;
}

static QString graphicsApiName()
{
    switch (QQuickWindow::graphicsApi()) {
    case QSGRendererInterface::Direct3D11:
        return QStringLiteral("Direct3D 11");
    case QSGRendererInterface::Direct3D12:
        return QStringLiteral("Direct3D 12");
    case QSGRendererInterface::OpenGL:
        return QStringLiteral("OpenGL");
    case QSGRendererInterface::Vulkan:
        return QStringLiteral("Vulkan");
    case QSGRendererInterface::Metal:
        return QStringLiteral("Metal");
    case QSGRendererInterface::Software:
        return QStringLiteral("software");
    default:
        return QStringLiteral("other");
    }
}

static QString aboutText()
{
    QStringList lines;
    lines << QStringLiteral("letitedit %1 (engine: Shotcut %2)").arg(buildName(), qApp->applicationVersion());
    lines << QStringLiteral("Windows: %1 (%2)").arg(QSysInfo::prettyProductName(), QSysInfo::kernelVersion());
    QString pc = QStringLiteral("PC: %1 logical cores").arg(QThread::idealThreadCount());
#ifdef Q_OS_WIN
    MEMORYSTATUSEX memory;
    memory.dwLength = sizeof(memory);
    if (GlobalMemoryStatusEx(&memory))
        pc += QStringLiteral(", %1 GB memory").arg(double(memory.ullTotalPhys) / (1024.0 * 1024 * 1024), 0, 'f', 1);
#endif
    lines << pc;
    QStringList cards;
    for (const GpuAdapterInfo &gpu : enumerateGpuAdapters())
        cards << gpu.name;
    lines << QStringLiteral("Graphics: %1 (drawing with %2, safe mode %3)")
                 .arg(cards.isEmpty() ? QStringLiteral("not known") : cards.join(QStringLiteral(", ")),
                      graphicsApiName(), Settings.safeMode() ? QStringLiteral("on") : QStringLiteral("off"));
    lines << QStringLiteral("Language: %1").arg(QLocale::system().name());
    return clean(lines.join(QLatin1Char('\n')));
}

static QString yesNo(bool value)
{
    return value ? QStringLiteral("yes") : QStringLiteral("no");
}

static QString aiText()
{
    const QJsonObject state = aiChatState();
    if (!state.value(QStringLiteral("installed")).toBool())
        return QStringLiteral("The AI chat isn't open in this window.");
    const QJsonObject choice = state.value(QStringLiteral("choice")).toObject();
    const QString engine = choice.value(QStringLiteral("engine")).toString(state.value(QStringLiteral("engine")).toString());
    QStringList lines;
    QString set = QStringLiteral("AI: %1").arg(aiEngineShortName(engine));
    QStringList how;
    if (!choice.value(QStringLiteral("model")).toString().isEmpty())
        how << QStringLiteral("model %1").arg(choice.value(QStringLiteral("model")).toString());
    if (!choice.value(QStringLiteral("effort")).toString().isEmpty())
        how << QStringLiteral("effort %1").arg(choice.value(QStringLiteral("effort")).toString());
    if (!how.isEmpty())
        set += QStringLiteral(" (set to %1)").arg(how.join(QStringLiteral(", ")));
    if (!state.value(QStringLiteral("active_model")).toString().isEmpty())
        set += QStringLiteral("; last answered with %1").arg(state.value(QStringLiteral("active_model")).toString());
    lines << set;
    lines << QStringLiteral("Working on a request: %1; waiting for your OK: %2; chat shown as %3")
                 .arg(yesNo(state.value(QStringLiteral("busy")).toBool()),
                      yesNo(state.value(QStringLiteral("waiting")).toBool()),
                      state.value(QStringLiteral("view_mode")).toString());
    const QJsonObject runner = state.value(QStringLiteral("new_video_runner")).toObject();
    lines << QStringLiteral("New video: %1")
                 .arg(state.value(QStringLiteral("new_video_chat")).toBool() || runner.value(QStringLiteral("working")).toBool()
                          ? QStringLiteral("this chat is making a video")
                          : QStringLiteral("not running"));
    const QJsonArray outcomes = state.value(QStringLiteral("outcomes")).toArray();
    if (!outcomes.isEmpty()) {
        lines << QStringLiteral("Last requests (newest last):");
        for (int i = qMax(0, int(outcomes.size()) - 3); i < outcomes.size(); ++i) {
            const QJsonObject o = outcomes.at(i).toObject();
            QString line = QStringLiteral("- %1 after %2 s, %3 edits")
                               .arg(o.value(QStringLiteral("outcome")).toString(),
                                    QString::number(qRound(o.value(QStringLiteral("seconds")).toDouble())),
                                    QString::number(o.value(QStringLiteral("changes")).toArray().size()));
            const QString error = o.value(QStringLiteral("error")).toString().simplified();
            if (!error.isEmpty())
                line += QStringLiteral(": ") + error.left(200);
            lines << line;
        }
    }
    return clean(lines.join(QLatin1Char('\n')));
}

static QString exitName(quint32 code)
{
    switch (code) {
    case 0xC0000005u:
        return QStringLiteral("access violation");
    case 0xC00000FDu:
        return QStringLiteral("stack overflow");
    case 0xC0000374u:
        return QStringLiteral("heap corruption");
    case 0xC0000409u:
        return QStringLiteral("stack buffer overrun or fast fail");
    case 0xC000001Du:
        return QStringLiteral("illegal instruction");
    case 0xC0000094u:
        return QStringLiteral("integer division by zero");
    case 0xC0000017u:
        return QStringLiteral("out of memory");
    case 0x80000003u:
        return QStringLiteral("breakpoint");
    case 0xC06D007Eu:
        return QStringLiteral("a program file (DLL) was not found");
    case 3u:
        return QStringLiteral("it stopped itself after an internal error (abort)");
    default:
        return QStringLiteral("exit code");
    }
}

static QString durationText(qint64 ms)
{
    const qint64 s = ms / 1000;
    if (s < 60)
        return QStringLiteral("%1 s").arg(s);
    if (s < 3600)
        return QStringLiteral("%1 min %2 s").arg(s / 60).arg(s % 60);
    return QStringLiteral("%1 h %2 min").arg(s / 3600).arg((s % 3600) / 60);
}

// The crash note's text (from crash/pending.json and the handler's crash/detail.txt).
static QString crashText(const QJsonObject &note, const QString &detail)
{
    QStringList lines;
    if (note.value(QStringLiteral("how")).toString() == QLatin1String("start-hang")) {
        lines << QStringLiteral("How it ended: the window didn't finish starting, so letitedit restarted it in safe mode");
    } else {
        const quint32 code = quint32(note.value(QStringLiteral("exit_code")).toDouble());
        lines << QStringLiteral("How it ended: %1 (0x%2)")
                     .arg(exitName(code), QStringLiteral("%1").arg(code, 8, 16, QLatin1Char('0')).toUpper());
    }
    if (note.contains(QStringLiteral("ran_ms")))
        lines << QStringLiteral("It had run for: %1").arg(durationText(qint64(note.value(QStringLiteral("ran_ms")).toDouble())));
    if (!note.value(QStringLiteral("when")).toString().isEmpty())
        lines << QStringLiteral("When: %1").arg(note.value(QStringLiteral("when")).toString());
    if (!note.value(QStringLiteral("build")).toString().isEmpty())
        lines << QStringLiteral("Build: %1").arg(note.value(QStringLiteral("build")).toString());
    if (note.value(QStringLiteral("earlier")).toInt() > 0)
        lines << QStringLiteral("Crashes before this one, not reported: %1").arg(note.value(QStringLiteral("earlier")).toInt());
    if (!detail.trimmed().isEmpty())
        lines << QStringLiteral("The crashing code (module + offset):") << detail.trimmed();
    return clean(lines.join(QLatin1Char('\n')));
}

static QString setupText(const QJsonObject &note)
{
    QStringList lines;
    lines << QStringLiteral("The setup step that went wrong: %1")
                 .arg(note.value(QStringLiteral("step")).toString(QStringLiteral("letitedit's Python tools")));
    if (!note.value(QStringLiteral("when")).toString().isEmpty())
        lines << QStringLiteral("When: %1").arg(note.value(QStringLiteral("when")).toString());
    const QString log = tailOf(setupDir() + QStringLiteral("/install-env.log"), 80);
    if (!log.isEmpty())
        lines << QStringLiteral("The last lines of the setup's log:") << log;
    return capFront(clean(lines.join(QLatin1Char('\n'))), kLogBytes);
}

// The crash or setup data a start-up note found, kept for the report window it opens.
static QJsonObject &pendingData()
{
    static QJsonObject data;
    return data;
}

QJsonObject parts(const Context &context)
{
    QJsonObject out;
    out[QStringLiteral("about")] = aboutText();
    const QJsonObject pending = pendingData();
    if (context.kind == QLatin1String("crash") && pending.contains(QStringLiteral("crash"))) {
        out[QStringLiteral("crash")] = pending.value(QStringLiteral("crash")).toString();
        out[QStringLiteral("log")] = pending.value(QStringLiteral("log")).toString();
    } else {
        out[QStringLiteral("log")] = capFront(clean(tailOf(appData() + QStringLiteral("/letitedit-log.txt"), kLogLines)), kLogBytes);
        out[QStringLiteral("ai")] = aiText();
    }
    if (context.kind == QLatin1String("setup") && pending.contains(QStringLiteral("setup")))
        out[QStringLiteral("setup")] = pending.value(QStringLiteral("setup")).toString();
    if (!context.screen.trimmed().isEmpty())
        out[QStringLiteral("screen")] = clean(context.screen.trimmed()).left(2000);
    return out;
}

QJsonObject report(const Context &context, const QJsonObject &parts, const QString &reportId)
{
    QJsonObject kept;
    for (auto it = parts.begin(); it != parts.end(); ++it)
        if (!it.value().toString().trimmed().isEmpty())
            kept.insert(it.key(), it.value().toString());
    return QJsonObject{{QStringLiteral("format"), QString::fromLatin1(kFormat)},
                       {QStringLiteral("report_id"), reportId},
                       {QStringLiteral("kind"), context.kind},
                       {QStringLiteral("from"), context.from},
                       {QStringLiteral("parts"), kept}};
}

static bool usableUrl(const QString &address)
{
    const QUrl url(address);
    if (!url.isValid() || !url.userInfo().isEmpty())
        return false;
    if (url.scheme() == QLatin1String("https"))
        return !url.host().isEmpty();
    // the local stand-in of the checks
    return url.scheme() == QLatin1String("http")
           && (url.host() == QLatin1String("127.0.0.1") || url.host() == QLatin1String("localhost"));
}

QString reportsUrl()
{
    QString address;
    if (qEnvironmentVariableIsSet("LETITEDIT_REPORTS_URL"))
        address = qEnvironmentVariable("LETITEDIT_REPORTS_URL").trimmed();
    else if (qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main")) == QLatin1String("main"))
        address = QString::fromLatin1(kReportsUrl);
    if (address.compare(QStringLiteral("off"), Qt::CaseInsensitive) == 0 || !usableUrl(address))
        return QString();
    while (address.endsWith(QLatin1Char('/')))
        address.chop(1);
    return address;
}

// ---- the report window ---------------------------------------------------------------------------------------------

namespace {

struct PartInfo
{
    QString key;
    QString title;
};

QList<PartInfo> partOrder(const Context &context)
{
    QList<PartInfo> order;
    if (context.kind == QLatin1String("crash"))
        order << PartInfo{QStringLiteral("crash"), QObject::tr("How letitedit closed")};
    if (context.kind == QLatin1String("setup"))
        order << PartInfo{QStringLiteral("setup"), QObject::tr("What went wrong in the setup")};
    order << PartInfo{QStringLiteral("screen"), QObject::tr("What the screen said")}
          << PartInfo{QStringLiteral("about"), QObject::tr("letitedit's version, Windows and your PC")}
          << PartInfo{QStringLiteral("log"), context.kind == QLatin1String("crash")
                                                 ? QObject::tr("The last lines of letitedit's log before it closed")
                                                 : QObject::tr("The last lines of letitedit's log")}
          << PartInfo{QStringLiteral("ai"), QObject::tr("What your AI was doing (not what was said)")};
    return order;
}

void keepReceipt(const QJsonObject &sent, const QString &deleteKey)
{
    const QString folder = appData() + QStringLiteral("/problem-reports");
    const QString id = sent.value(QStringLiteral("report_id")).toString();
    writeJson(folder + QStringLiteral("/") + id + QStringLiteral(".json"), sent);
    QFile file(folder + QStringLiteral("/sent.json"));
    QJsonArray receipts;
    if (file.open(QIODevice::ReadOnly)) {
        receipts = QJsonDocument::fromJson(file.readAll()).array();
        file.close();
    }
    receipts.append(QJsonObject{{QStringLiteral("report_id"), id},
                                {QStringLiteral("kind"), sent.value(QStringLiteral("kind"))},
                                {QStringLiteral("sent_at"), QDateTime::currentDateTimeUtc().toString(Qt::ISODate)},
                                {QStringLiteral("delete_key"), deleteKey}});
    writeJson(folder + QStringLiteral("/sent.json"), receipts);
}

} // namespace

void showDialog(QWidget *parent, const Context &context)
{
    auto dialog = new QDialog(parent);
    dialog->setObjectName(QStringLiteral("problemReportDialog"));
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowTitle(context.kind == QLatin1String("crash")   ? QObject::tr("Report the crash")
                           : context.kind == QLatin1String("setup") ? QObject::tr("Report the setup problem")
                                                                    : QObject::tr("Report a problem"));
    dialog->resize(680, 760);
    const QString target = reportsUrl();
    const QString reportId = randomHex();
    const QString deleteKey = randomHex();
    const QJsonObject built = parts(context);

    auto column = new QVBoxLayout(dialog);
    auto intro = new QLabel(QObject::tr("Tell us what happened. Below is everything this report holds: untick a part to "
                                        "leave it out, or change its text. Nothing is sent until you press Send."),
                            dialog);
    intro->setObjectName(QStringLiteral("problemReportIntro"));
    intro->setWordWrap(true);
    column->addWidget(intro);
    auto wordsLabel = new QLabel(QObject::tr("What happened?"), dialog);
    column->addWidget(wordsLabel);
    auto words = new QPlainTextEdit(dialog);
    words->setObjectName(QStringLiteral("problemReportWords"));
    words->setPlaceholderText(QObject::tr("What were you doing, and what went wrong?"));
    words->setMaximumHeight(110);
    column->addWidget(words);

    auto scroll = new QScrollArea(dialog);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto holder = new QWidget(scroll);
    auto partsColumn = new QVBoxLayout(holder);
    partsColumn->setContentsMargins(0, 0, 0, 0);
    QHash<QString, QCheckBox *> ticks;
    QHash<QString, QPlainTextEdit *> texts;
    for (const PartInfo &info : partOrder(context)) {
        if (!built.contains(info.key))
            continue;
        auto tick = new QCheckBox(info.title, holder);
        tick->setObjectName(QStringLiteral("problemReportPart_") + info.key);
        tick->setChecked(true);
        partsColumn->addWidget(tick);
        auto text = new QPlainTextEdit(built.value(info.key).toString(), holder);
        text->setObjectName(QStringLiteral("problemReportText_") + info.key);
        text->setLineWrapMode(info.key == QLatin1String("log") ? QPlainTextEdit::NoWrap : QPlainTextEdit::WidgetWidth);
        const int lines = qMin(info.key == QLatin1String("log") ? 10 : 8,
                               int(built.value(info.key).toString().count(QLatin1Char('\n'))) + 2);
        text->setFixedHeight(text->fontMetrics().lineSpacing() * lines + 14);
        if (info.key == QLatin1String("log")) {
            // the newest lines in view, from the start of the line (the log doesn't wrap)
            text->moveCursor(QTextCursor::End);
            text->moveCursor(QTextCursor::StartOfLine);
        }
        partsColumn->addWidget(text);
        QObject::connect(tick, &QCheckBox::toggled, text, &QWidget::setEnabled);
        ticks.insert(info.key, tick);
        texts.insert(info.key, text);
    }
    partsColumn->addStretch(1);
    scroll->setWidget(holder);
    column->addWidget(scroll, 1);

    auto never = new QLabel(QObject::tr("Never sent: your videos, pictures or project files, what you and your AI wrote in "
                                        "the chat, your AI sign-in, your name, e-mail or Windows user name, and file paths "
                                        "(letitedit puts <path>, <user> and so on in their place). Also sent: a random "
                                        "number for this report."),
                            dialog);
    never->setObjectName(QStringLiteral("problemReportNever"));
    never->setWordWrap(true);
    never->setProperty("studioMuted", true);
    column->addWidget(never);
    auto where = new QLabel(dialog);
    where->setObjectName(QStringLiteral("problemReportWhere"));
    where->setWordWrap(true);
    where->setProperty("studioMuted", true);
    where->setText(target.isEmpty()
                       ? QObject::tr("This version can't send reports yet. Save the report as a file and e-mail it to "
                                     "%1.").arg(QString::fromLatin1(kTeamEmail))
                       : QObject::tr("It goes to letitedit's report server (%1) and is deleted after 90 days. Privacy: "
                                     "letitedit.app/privacy").arg(QUrl(target).host()));
    column->addWidget(where);
    auto status = new QLabel(dialog);
    status->setObjectName(QStringLiteral("problemReportStatus"));
    status->setWordWrap(true);
    status->setTextInteractionFlags(Qt::TextSelectableByMouse);
    column->addWidget(status);

    auto buttons = new QDialogButtonBox(dialog);
    auto save = buttons->addButton(QObject::tr("Save as a file..."), QDialogButtonBox::ActionRole);
    save->setObjectName(QStringLiteral("problemReportSave"));
    auto send = buttons->addButton(QObject::tr("Send"), QDialogButtonBox::AcceptRole);
    send->setObjectName(QStringLiteral("problemReportSend"));
    send->setVisible(!target.isEmpty());
    send->setDefault(!target.isEmpty());
    auto close = buttons->addButton(QDialogButtonBox::Close);
    close->setObjectName(QStringLiteral("problemReportClose"));
    column->addWidget(buttons);
    QObject::connect(close, &QPushButton::clicked, dialog, &QDialog::reject);

    // What the window shows now, cleaned once more; false (and the cleaned text shown) when the cleaning changed it.
    auto settle = [=]() -> bool {
        bool changed = false;
        QString said = words->toPlainText();
        if (said.size() > kMaxWords) {
            status->setText(QObject::tr("What happened? is %1 characters long; at most %2 fit. Please shorten it.")
                                .arg(said.size()).arg(kMaxWords));
            return false;
        }
        const QString cleanSaid = clean(said);
        if (cleanSaid != said) {
            words->setPlainText(cleanSaid);
            changed = true;
        }
        for (auto it = texts.begin(); it != texts.end(); ++it) {
            if (!ticks.value(it.key())->isChecked())
                continue;
            const QString now = it.value()->toPlainText();
            const QString cleaned = clean(now);
            if (cleaned != now) {
                it.value()->setPlainText(cleaned);
                changed = true;
            }
        }
        if (changed)
            status->setText(QObject::tr("letitedit took file paths, names, e-mail addresses or keys out of the text "
                                        "(shown now). Look it over, then press %1 again.")
                                .arg(target.isEmpty() ? QObject::tr("Save as a file") : QObject::tr("Send")));
        return !changed;
    };
    auto assemble = [=]() -> QJsonObject {
        QJsonObject chosen;
        if (!words->toPlainText().trimmed().isEmpty())
            chosen[QStringLiteral("words")] = words->toPlainText().trimmed();
        for (auto it = texts.begin(); it != texts.end(); ++it)
            if (ticks.value(it.key())->isChecked())
                chosen[it.key()] = it.value()->toPlainText();
        return report(context, chosen, reportId);
    };

    QObject::connect(save, &QPushButton::clicked, dialog, [=]() {
        if (!settle())
            return;
        QString file = qEnvironmentVariableIsSet("LETITEDIT_QA") ? qEnvironmentVariable("LETITEDIT_QA_REPORT_SAVE") : QString();
        if (file.isEmpty())
            file = QFileDialog::getSaveFileName(dialog, QObject::tr("Save the report"),
                                                QDir::home().filePath(QStringLiteral("letitedit report %1.json")
                                                                          .arg(reportId.left(8))),
                                                QObject::tr("Report (*.json)"));
        if (file.isEmpty())
            return;
        const QJsonObject sent = assemble();
        QSaveFile out(file);
        if (out.open(QIODevice::WriteOnly) && out.write(QJsonDocument(sent).toJson()) >= 0 && out.commit())
            status->setText(QObject::tr("Saved. Attach the file to an e-mail to %1.").arg(QString::fromLatin1(kTeamEmail)));
        else
            status->setText(QObject::tr("Couldn't save the file there. Try another folder."));
    });

    QObject::connect(send, &QPushButton::clicked, dialog, [=]() {
        if (!settle())
            return;
        const QJsonObject sent = assemble();
        const QByteArray body = QJsonDocument(sent).toJson(QJsonDocument::Compact);
        if (body.size() > kMaxReportBytes) {
            status->setText(QObject::tr("This report is too big to send (%1 KB; at most %2 KB). Shorten or untick a part, "
                                        "or save it as a file.")
                                .arg(body.size() / 1024).arg(kMaxReportBytes / 1024));
            return;
        }
        QNetworkRequest request{QUrl(target + QStringLiteral("/v1/reports"))};
        request.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
        request.setHeader(QNetworkRequest::UserAgentHeader, QStringLiteral("letitedit/%1").arg(buildName()));
        request.setRawHeader("X-Delete-Key", deleteKey.toLatin1());
        request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
        request.setTransferTimeout(20000);
        auto network = new QNetworkAccessManager(dialog);
        send->setEnabled(false);
        status->setText(QObject::tr("Sending..."));
        QNetworkReply *reply = network->post(request, body);
        QObject::connect(reply, &QNetworkReply::finished, dialog, [=]() {
            reply->deleteLater();
            const QJsonObject answer = QJsonDocument::fromJson(reply->readAll()).object();
            const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            if (reply->error() == QNetworkReply::NoError && answer.value(QStringLiteral("ok")).toBool()) {
                keepReceipt(sent, deleteKey);
                status->setText(QObject::tr("Sent. Thank you! Your report number is %1 (quote it if you e-mail us).")
                                    .arg(reportId.left(8)));
                send->setText(QObject::tr("Sent"));
                LOG_INFO() << "problem report sent:" << reportId.left(8);
                return;
            }
            send->setEnabled(true);
            const QString why = !answer.value(QStringLiteral("error")).toString().isEmpty()
                                    ? answer.value(QStringLiteral("error")).toString()
                                : code ? QStringLiteral("the server answered %1").arg(code)
                                       : reply->errorString();
            status->setText(QObject::tr("Couldn't send it just now (%1). Your report is still here: try again, or save it "
                                        "as a file and e-mail it to %2.")
                                .arg(why.left(200), QString::fromLatin1(kTeamEmail)));
            LOG_WARNING() << "problem report not sent:" << code << reply->error();
        });
    });
    dialog->show();
}

void addMenuItems(QWidget *window, QMenu *help)
{
    auto action = new QAction(QObject::tr("Report a problem..."), window);
    action->setObjectName(QStringLiteral("actionReportProblem"));
    QObject::connect(action, &QAction::triggered, window, [window]() { showDialog(window); });
    help->addAction(action);
}

// ---- notes at start-up ---------------------------------------------------------------------------------------------

static void showNote(QWidget *window, const QString &title, const QString &text, const std::function<void()> &look,
                     const std::function<void()> &answered)
{
    auto note = new QDialog(window);
    note->setObjectName(QStringLiteral("problemNoteDialog"));
    note->setAttribute(Qt::WA_DeleteOnClose);
    // never takes the keyboard from what the person is doing
    note->setAttribute(Qt::WA_ShowWithoutActivating);
    note->setModal(false);
    note->setWindowTitle(title);
    auto column = new QVBoxLayout(note);
    auto label = new QLabel(text, note);
    label->setObjectName(QStringLiteral("problemNoteText"));
    label->setWordWrap(true);
    label->setMinimumWidth(380);
    column->addWidget(label);
    auto buttons = new QDialogButtonBox(note);
    auto open = buttons->addButton(QObject::tr("Look at the report..."), QDialogButtonBox::AcceptRole);
    open->setObjectName(QStringLiteral("problemNoteLook"));
    auto skip = buttons->addButton(QObject::tr("Don't send"), QDialogButtonBox::RejectRole);
    skip->setObjectName(QStringLiteral("problemNoteSkip"));
    column->addWidget(buttons);
    QObject::connect(open, &QPushButton::clicked, note, &QDialog::accept);
    QObject::connect(skip, &QPushButton::clicked, note, &QDialog::reject);
    // either answer (or closing it) clears the note: it is never asked twice for one crash
    QObject::connect(note, &QDialog::finished, window, [look, answered](int result) {
        answered();
        if (result == QDialog::Accepted)
            look();
    });
    note->show();
}

static void forgetCrash()
{
    const QString dir = crashDir();
    for (const char *name : {"pending.json", "log-tail.txt", "detail.txt"})
        QFile::remove(dir + QLatin1Char('/') + QLatin1String(name));
}

void checkAtStart(QWidget *window)
{
    const QString dir = crashDir();
    QJsonObject note = readJson(dir + QStringLiteral("/pending.json"));
    const QFileInfo detailFile(dir + QStringLiteral("/detail.txt"));
    // a crash after a restart (no watchdog then): the handler's note alone, with the log of that session
    if (note.isEmpty() && detailFile.exists()) {
        note = QJsonObject{{QStringLiteral("how"), QStringLiteral("crash")},
                           {QStringLiteral("when"), detailFile.lastModified().toString(QStringLiteral("yyyy-MM-dd HH:mm"))}};
        QFile detail(detailFile.absoluteFilePath());
        if (detail.open(QIODevice::ReadOnly)) {
            const QString first = QString::fromUtf8(detail.readLine());
            static const QRegularExpression code(QStringLiteral("0x([0-9A-Fa-f]{8})"));
            const auto m = code.match(first);
            if (m.hasMatch())
                note[QStringLiteral("exit_code")] = double(m.captured(1).toUInt(nullptr, 16));
        }
        note[QStringLiteral("log_file")] = appData() + QStringLiteral("/letitedit-log.bak");
    }
    if (!note.isEmpty()) {
        const QDateTime when = QFileInfo(note.contains(QStringLiteral("log_file")) ? detailFile.absoluteFilePath()
                                                                                    : dir + QStringLiteral("/pending.json"))
                                   .lastModified();
        if (when.daysTo(QDateTime::currentDateTime()) > kCrashNoteDays) {
            forgetCrash();
        } else {
            QString detail;
            QFile file(detailFile.absoluteFilePath());
            if (file.open(QIODevice::ReadOnly))
                detail = QString::fromUtf8(file.read(16 * 1024));
            const QString logFile = note.contains(QStringLiteral("log_file")) ? note.value(QStringLiteral("log_file")).toString()
                                                                              : dir + QStringLiteral("/log-tail.txt");
            pendingData() = QJsonObject{{QStringLiteral("crash"), crashText(note, detail)},
                                        {QStringLiteral("log"), capFront(clean(tailOf(logFile, kLogLines)), kLogBytes)}};
            LOG_INFO() << "letitedit closed unexpectedly last time: offering a crash report";
            showNote(window, QObject::tr("letitedit closed unexpectedly"),
                     QObject::tr("letitedit closed unexpectedly last time. A report helps us fix it: you'll see "
                                 "exactly what it holds before anything is sent."),
                     [window]() { showDialog(window, Context{QStringLiteral("after-crash"), QStringLiteral("crash"), QString()}); },
                     []() { forgetCrash(); });
            return;
        }
    }
    // the install's own setup: only the person's main window asks (never a test or Studio window)
    const bool mainWindow = qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main")) == QLatin1String("main")
                            || qEnvironmentVariableIsSet("LETITEDIT_SETUP_DIR");
    const QString setupNote = setupDir() + QStringLiteral("/setup-problem.json");
    if (mainWindow && QFileInfo::exists(setupNote)) {
        const QJsonObject setup = readJson(setupNote);
        pendingData() = QJsonObject{{QStringLiteral("setup"), setupText(setup)}};
        showNote(window, QObject::tr("letitedit's setup had a problem"),
                 QObject::tr("Part of letitedit's setup didn't finish when it was installed. A report helps us fix it: "
                             "you'll see exactly what it holds before anything is sent."),
                 [window]() { showDialog(window, Context{QStringLiteral("after-setup"), QStringLiteral("setup"), QString()}); },
                 [setupNote]() { QFile::rename(setupNote, setupNote + QStringLiteral(".answered")); });
    }
}

// ---- crash notes ---------------------------------------------------------------------------------------------------

void recordChildEnd(const QString &base, bool crashExit, int exitCode, qint64 ranMs, bool hungAtStart)
{
    const quint32 code = quint32(exitCode);
    const bool crashed = hungAtStart || crashExit || code == 3u || code >= 0x80000000u;
    if (!crashed || base.isEmpty())
        return;
    const QString dir = crashDir(base);
    QDir().mkpath(dir);
    // a handler's note from an earlier session doesn't belong to this crash
    const QFileInfo detail(dir + QStringLiteral("/detail.txt"));
    if (detail.exists() && detail.lastModified() < QDateTime::currentDateTime().addMSecs(-ranMs - 5000))
        QFile::remove(detail.absoluteFilePath());
    const QJsonObject before = readJson(dir + QStringLiteral("/pending.json"));
    QJsonObject note{{QStringLiteral("format"), QStringLiteral("letitedit-crash-note/1")},
                     {QStringLiteral("how"), hungAtStart ? QStringLiteral("start-hang") : QStringLiteral("crash")},
                     {QStringLiteral("exit_code"), double(code)},
                     {QStringLiteral("ran_ms"), double(ranMs)},
                     {QStringLiteral("when"), QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd HH:mm"))},
                     {QStringLiteral("build"), buildName()}};
    if (!before.isEmpty())
        note[QStringLiteral("earlier")] = before.value(QStringLiteral("earlier")).toInt() + 1;
    // the log of the session that crashed, before the next start moves it aside
    QFile log(QDir::fromNativeSeparators(base) + QStringLiteral("/letitedit-log.txt"));
    if (log.open(QIODevice::ReadOnly)) {
        constexpr qint64 window = 256 * 1024;
        if (log.size() > window)
            log.seek(log.size() - window);
        QFile tail(dir + QStringLiteral("/log-tail.txt"));
        if (tail.open(QIODevice::WriteOnly | QIODevice::Truncate))
            tail.write(log.read(window));
    }
    writeJson(dir + QStringLiteral("/pending.json"), note);
}

#ifdef Q_OS_WIN
static wchar_t g_detailPath[1024];
static LPTOP_LEVEL_EXCEPTION_FILTER g_previous = nullptr;

static int putText(char *out, int at, int size, const char *text)
{
    while (*text && at < size - 1)
        out[at++] = *text++;
    return at;
}

static int putHex(char *out, int at, int size, unsigned long long value, int digits)
{
    static const char hex[] = "0123456789ABCDEF";
    char buffer[17];
    int n = 0;
    do {
        buffer[n++] = hex[value & 0xF];
        value >>= 4;
    } while ((value || n < digits) && n < 16);
    at = putText(out, at, size, "0x");
    while (n > 0 && at < size - 1)
        out[at++] = buffer[--n];
    return at;
}

// "Qt6Core.dll+0x1A2B" for an address (only the module's file name, never its folder)
static int putFrame(char *out, int at, int size, void *address)
{
    HMODULE module = nullptr;
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(address), &module)
        && module) {
        wchar_t name[MAX_PATH];
        const DWORD n = GetModuleFileNameW(module, name, MAX_PATH);
        DWORD start = 0;
        for (DWORD i = 0; i < n; ++i)
            if (name[i] == L'\\' || name[i] == L'/')
                start = i + 1;
        for (DWORD i = start; i < n && at < size - 1; ++i)
            out[at++] = name[i] < 128 ? char(name[i]) : '?';
        at = putText(out, at, size, "+");
        return putHex(out, at, size, reinterpret_cast<unsigned long long>(address)
                                         - reinterpret_cast<unsigned long long>(module), 1);
    }
    return putHex(out, at, size, reinterpret_cast<unsigned long long>(address), 1);
}

static LONG WINAPI lastChance(EXCEPTION_POINTERS *info)
{
    const DWORD code = info && info->ExceptionRecord ? info->ExceptionRecord->ExceptionCode : 0;
    // not an error (GCC's own C++ exceptions, thread names, debug prints): as before
    if (code < 0x80000000u)
        return g_previous ? g_previous(info) : EXCEPTION_CONTINUE_SEARCH;
    static volatile LONG once = 0;
    if (InterlockedExchange(&once, 1) == 0) {
        static char text[8192];
        int at = 0;
        const int size = int(sizeof(text));
        at = putText(text, at, size, "exception ");
        at = putHex(text, at, size, code, 8);
        at = putText(text, at, size, " at ");
        at = putFrame(text, at, size, info->ExceptionRecord->ExceptionAddress);
        if (code == 0xC0000005u && info->ExceptionRecord->NumberParameters >= 2) {
            const ULONG_PTR kind = info->ExceptionRecord->ExceptionInformation[0];
            at = putText(text, at, size, kind == 0 ? " (reading " : kind == 1 ? " (writing " : " (running ");
            at = putHex(text, at, size, info->ExceptionRecord->ExceptionInformation[1], 1);
            at = putText(text, at, size, ")");
        }
        at = putText(text, at, size, "\n");
        void *frames[40];
        const USHORT count = RtlCaptureStackBackTrace(0, 40, frames, nullptr);
        for (USHORT i = 0; i < count; ++i) {
            at = putText(text, at, size, "  ");
            at = putFrame(text, at, size, frames[i]);
            at = putText(text, at, size, "\n");
        }
        HANDLE file = CreateFileW(g_detailPath, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file != INVALID_HANDLE_VALUE) {
            DWORD written = 0;
            WriteFile(file, text, DWORD(at), &written, nullptr);
            CloseHandle(file);
        }
    }
    if (g_previous) {
        const LONG handled = g_previous(info);
        if (handled == EXCEPTION_CONTINUE_EXECUTION)
            return handled;
    }
    // ends here with the same code, so no "stopped working" box holds the window open; the watchdog sees the crash
    TerminateProcess(GetCurrentProcess(), code);
    return EXCEPTION_EXECUTE_HANDLER;
}
#endif

void installCrashHandler(const QString &base)
{
#ifdef Q_OS_WIN
    const QString dir = crashDir(base);
    QDir().mkpath(dir);
    const QString file = QDir::toNativeSeparators(dir + QStringLiteral("/detail.txt"));
    if (file.size() >= int(sizeof(g_detailPath) / sizeof(wchar_t)))
        return;
    file.toWCharArray(g_detailPath);
    g_detailPath[file.size()] = L'\0';
    g_previous = SetUnhandledExceptionFilter(lastChance);
#else
    Q_UNUSED(base);
#endif
}

// ---- for the checks ------------------------------------------------------------------------------------------------

QJsonObject qaReport(const QJsonObject &params)
{
    if (params.contains(QStringLiteral("clean")))
        return QJsonObject{{QStringLiteral("cleaned"), clean(params.value(QStringLiteral("clean")).toString())}};
    Context context;
    context.from = params.value(QStringLiteral("from")).toString(context.from);
    context.kind = params.value(QStringLiteral("kind")).toString(context.kind);
    context.screen = params.value(QStringLiteral("screen")).toString();
    QJsonObject built = parts(context);
    if (params.contains(QStringLiteral("log")))
        built[QStringLiteral("log")] = capFront(clean(params.value(QStringLiteral("log")).toString()), kLogBytes);
    if (params.contains(QStringLiteral("words")))
        built[QStringLiteral("words")] = clean(params.value(QStringLiteral("words")).toString());
    return QJsonObject{{QStringLiteral("parts"), built},
                       {QStringLiteral("report"), report(context, built, randomHex())},
                       {QStringLiteral("target"), reportsUrl()},
                       {QStringLiteral("build"), buildName()}};
}

void qaCrash()
{
    // after the bridge's answer has gone out
    QTimer::singleShot(300, qApp, []() {
        volatile int *nowhere = nullptr;
        *nowhere = 368;
    });
}

} // namespace ProblemReport
