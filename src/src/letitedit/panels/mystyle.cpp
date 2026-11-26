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

#include "letitedit/panels/mystyle.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/newvideo/learnlooks.h"

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "docks/subtitlesdock.h"
#include "letitedit/workspace/focusworkspace.h"
#include "letitedit/letitedit.h"
#include "mainwindow.h"
#include "mltcontroller.h"

#include <QCheckBox>
#include <QColor>
#include <QComboBox>
#include <QDateTime>
#include <QDialog>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QPointer>
#include <QSignalBlocker>
#include <QRegularExpression>
#include <QProcess>
#include <QHash>
#include <QSet>
#include <QSharedPointer>
#include <QTimer>
#include <QSaveFile>
#include <QScrollArea>
#include <QTabWidget>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QUndoCommand>
#include <QUuid>
#include <QVBoxLayout>

#include <cmath>

namespace MyStyle {

namespace {

const char *kCaptionKeys[] = {"family", "weight", "style", "fgcolour", "bgcolour", "olcolour", "halign"};
const char *kSizeKeys[] = {"size", "outline", "pad"};
const char *kLookProperty = "letitedit_ai:look";

// Shotcut colours are #AARRGGBB; style packs write #RRGGBB, or #RRGGBBAA when not solid.
QString packColour(const QString &shotcut)
{
    const QColor c(shotcut);
    if (!c.isValid())
        return QString();
    QString hex = c.name(QColor::HexRgb).toUpper();
    if (c.alpha() < 255)
        hex += QStringLiteral("%1").arg(c.alpha(), 2, 16, QLatin1Char('0')).toUpper();
    return hex;
}

// Pause length and music level by name, the same numbers the buttons and the AI's style packs use.
double maxPause(const QString &mode)
{
    return mode == QLatin1String("gentle") ? 0.6 : mode == QLatin1String("tight") ? 0.2 : 0.35;
}

QString pythonExe()
{
    return aiChatSettings().value("python").toString();
}

QJsonObject lookRequest(const QJsonObject &request, QString *why = nullptr)
{
    QTemporaryDir temp;
    QFile file(temp.filePath(QStringLiteral("request.json")));
    if (!temp.isValid() || !file.open(QIODevice::WriteOnly)) {
        if (why)
            *why = QObject::tr("could not write a temporary Look request");
        return {};
    }
    file.write(QJsonDocument(request).toJson());
    file.close();
    QByteArray printed;
    const bool ok = !pythonExe().isEmpty()
                    && leRun(pythonExe(), {aiRootPath(QStringLiteral("bridge/look_library.py")),
                                          QStringLiteral("--request"), file.fileName()},
                             nullptr, &printed, 30000);
    const int brace = printed.indexOf('{');
    const QJsonObject result = brace >= 0 ? QJsonDocument::fromJson(printed.mid(brace)).object() : QJsonObject();
    if (why)
        *why = ok ? QString() : result.value("error").toString(QObject::tr("the Look tools did not answer"));
    return ok ? result : QJsonObject();
}

QJsonArray personalLooks()
{
    QJsonArray result;
    for (const auto &item : lookRequest({{"action", "list"}}).value("looks").toArray())
        if (item.toObject().value("personal").toBool())
            result.append(item);
    return result;
}

QString lookTitle(const QString &identity)
{
    for (const auto &item : personalLooks()) {
        const QJsonObject card = item.toObject();
        if (card.value("id").toString() == identity)
            return card.value("label").toString(identity);
    }
    return identity;
}

bool personalLookExists(const QString &identity)
{
    return identity.startsWith(QLatin1String("mine-")) && !folder().isEmpty()
           && QFileInfo::exists(folder() + QLatin1Char('/') + identity + QStringLiteral("/look.json"));
}

QStringList writeLook(QString &identity, const QJsonObject &changes, QString *why,
                      const QJsonObject &assets = {}, const QString &revision = {})
{
    const bool exists = personalLookExists(identity);
    QJsonObject request{{"action", exists ? "update" : "create"}, {"assets", assets}};
    if (exists) {
        request["identity"] = identity;
        request["changes"] = changes;
        if (!revision.isEmpty())
            request["expected_revision"] = revision;
        if (changes.contains("label"))
            request["title"] = changes.value("label");
    } else {
        request["title"] = changes.value("label").toString(identity);
        request["values"] = changes;
    }
    const QJsonObject saved = lookRequest(request, why);
    if (!saved.value("id").toString().isEmpty())
        identity = saved.value("id").toString();
    return {};
}

QJsonObject appSettings(const QString &identity)
{
    return lookRequest({{"action", "settings"}, {"identity", identity}})
        .value("values").toObject().value("app").toObject();
}

// The caption look and the sound and pause settings, as changes for style.yaml (sizes in pixels on a 1080-high
// frame, the way packs keep them).
QJsonObject lookChanges(const QVariantMap &captions, double height, const QVariantMap &app)
{
    const auto px = [&](const char *key) {
        return qRound(captions.value(key).toDouble() * qMin(double(MLT.profile().width()), height) * 1080.0 / height);
    };
    const int volume = app.value("music_volume").toInt();
    QJsonObject caps{{"font", "captions"},
                     {"size", px("size")},
                     {"fill", packColour(captions.value("fgcolour").toString())},
                     {"pad", px("pad")}};
    const QColor outline(captions.value("olcolour").toString());
    if (px("outline") > 0 && outline.alpha() > 0)
        caps["outline"] = QJsonObject{{"color", packColour(outline.name(QColor::HexArgb))}, {"width", px("outline")}};
    else
        caps["outline"] = QJsonValue::Null;
    const QColor box(captions.value("bgcolour").toString());
    caps["background"] = box.alpha() > 0 ? QJsonValue(packColour(box.name(QColor::HexArgb))) : QJsonValue::Null;
    // The place on screen suits frames of the shape it was set on; on the other shape the usual place is used.
    if (!captions.value("geometry").toString().isEmpty()) {
        caps["geometry"] = captions.value("geometry").toString();
        caps["halign"] = captions.value("halign").toString();
        caps["valign"] = captions.value("valign").toString();
        caps["shape"] = captions.value("tall").toBool() ? "tall" : "wide";
    }
    return QJsonObject{
        {"fonts",
         QJsonObject{{"captions",
                      QJsonObject{{"family", captions.value("family").toString()}, {"weight", captions.value("weight").toInt()}}}}},
        {"captions", caps},
        {"music",
         QJsonObject{{"zones",
                      QJsonObject{{"talk", volume == 0 ? -22.0 : volume == 2 ? -14.0 : -18.0},
                                  {"montage", volume == 0 ? -10.0 : volume == 2 ? -3.0 : -6.0}}},
                     {"duck_under_speech", app.value("duck").toBool()}}},
        {"editing", QJsonObject{{"max_pause", maxPause(app.value("pauses").toString())}}},
        {"export", QJsonObject{{"loudness", -14}}}};
}

// The pack as the AI's tools read it (every default filled in), as the app's settings.
QVariantMap fromPack(const QString &name)
{
    const QString code = QStringLiteral(
        "import sys, json\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import look_library\n"
        "k = look_library.kit(sys.argv[2])\n"
        "own = k.caption_preferences\n"
        "print(json.dumps({'captions': k.caption_props(int(sys.argv[3]), int(sys.argv[4])),"
        " 'music': k.get('music') or {}, 'editing': k.get('editing') or {}, 'own_look': own,"
        " 'corrections': (k.get('captions') or {}).get('corrections') or {}}, default=str))\n");
    QByteArray printed;
    const int w = MLT.profile().width(), h = MLT.profile().height();
    if (pythonExe().isEmpty()
        || !leRun(pythonExe(),
                  {"-c", code, aiRootPath(QStringLiteral("bridge")), name,
                   QString::number(w), QString::number(h)},
                  nullptr,
                  &printed,
                  30000))
        return {};
    const QVariantMap pack = QJsonDocument::fromJson(printed.mid(printed.indexOf('{'))).toVariant().toMap();
    if (pack.isEmpty())
        return {};
    const QVariantMap props = pack.value("captions").toMap();
    const double shortSide = qMin(w, h);
    QVariantMap custom;
    for (const char *key : kCaptionKeys)
        custom[key] = props.value(key).toString();
    QVariantMap heights;
    for (const char *key : kSizeKeys) {
        custom[key] = props.value(key).toDouble() / shortSide;
        heights[key] = props.value(key).toDouble() / h;
    }
    custom["heights"] = heights;
    // A box given in pixels for another frame size can land off screen here: then the usual place is used.
    const QStringList box = props.value("geometry").toString().split(QRegularExpression(QStringLiteral("[ /:x]")),
                                                                      Qt::SkipEmptyParts);
    const bool fits = box.size() >= 4 && !box[0].endsWith('%')
                          ? box[0].toDouble() + box[2].toDouble() <= w * 1.02
                                && box[1].toDouble() + box[3].toDouble() <= h * 1.02
                          : true;
    if (fits) {
        custom["geometry"] = props.value("geometry");
        custom["valign"] = props.value("valign");
    }
    custom["tall"] = w < h;
    const double talk = pack.value("music").toMap().value("zones").toMap().value("talk", -18.0).toDouble();
    const double pause = pack.value("editing").toMap().value("max_pause", 0.35).toDouble();
    QStringList words;
    const QVariantMap corrections = pack.value("corrections").toMap();
    for (auto it = corrections.cbegin(); it != corrections.cend(); ++it)
        words << it.key() + QLatin1Char('\t') + it.value().toString();
    // a style that never set a caption look leaves the video's captions as they are
    if (!pack.value("own_look").toBool())
        custom.clear();
    return {{"captions", custom},
            {"music_volume", talk <= -20.0 ? 0 : talk >= -16.0 ? 2 : 1},
            {"duck", pack.value("music").toMap().value("duck_under_speech", true)},
            {"pauses", pause >= 0.5 ? "gentle" : pause < 0.28 ? "tight" : "normal"},
            {"words", words}};
}

// The words captions should spell the person's way, from the app's list (heard<TAB>written rows) to the pack's
// captions.corrections mapping and back.
QJsonObject correctionsFrom(const QStringList &rows)
{
    QJsonObject out;
    for (const auto &row : rows) {
        const int tab = row.indexOf(QLatin1Char('\t'));
        if (tab > 0)
            out.insert(row.left(tab), row.mid(tab + 1));
    }
    return out;
}

// Properties of the project itself (on the timeline's tractor, saved in the .mlt): letitedit_ai:style and the like.
// A null value removes the property.
class ProjectPropertiesCommand : public QUndoCommand
{
public:
    ProjectPropertiesCommand(const QJsonObject &after, const QString &label)
        : QUndoCommand(label)
        , m_after(after)
    {
        auto *tractor = MAIN.multitrack();
        for (auto it = after.begin(); it != after.end(); ++it) {
            const QByteArray key = it.key().toUtf8();
            const char *value = tractor ? tractor->get(key.constData()) : nullptr;
            m_before.insert(it.key(), value ? QJsonValue(QString::fromUtf8(value)) : QJsonValue(QJsonValue::Null));
        }
    }
    void redo() override { set(m_after); }
    void undo() override { set(m_before); }

private:
    static void set(const QJsonObject &props)
    {
        auto *tractor = MAIN.multitrack();
        if (!tractor)
            return;
        for (auto it = props.begin(); it != props.end(); ++it) {
            const QByteArray key = it.key().toUtf8();
            if (it.value().isNull() || it.value().isUndefined())
                tractor->Mlt::Properties::clear(key.constData());
            else
                tractor->set(key.constData(), it.value().toVariant().toString().toUtf8().constData());
        }
    }
    QJsonObject m_before, m_after;
};

QString safeName(const QString &raw)
{
    return raw.simplified();
}

} // namespace

QString folder()
{
    static const QString root = lookRequest({{"action", "location"}}).value("root").toString();
    return root;
}

QStringList styles()
{
    QStringList names;
    for (const auto &item : personalLooks())
        names << item.toObject().value("id").toString();
    return names;
}

QString active()
{
    const QString identity = leSettings().value("looks/active").toString();
    return identity.isEmpty() ? legacyLook(leSettings().value("style/active").toString()) : identity;
}

QString legacyLook(const QString &name)
{
    if (name.isEmpty())
        return {};
    if (name.startsWith(QLatin1String("mine-")))
        return name;
    return lookRequest({{"action", "project"}, {"project", QJsonObject{{"style", name}}}}).value("id").toString();
}

QString projectStyle(MainWindow *window)
{
    auto *tractor = window ? window->multitrack() : nullptr;
    if (!tractor)
        return {};
    const QString identity = QString::fromUtf8(tractor->get(kLookProperty));
    if (!identity.isEmpty())
        return identity;
    QJsonObject metadata;
    for (int index = 0; index < tractor->Mlt::Properties::count(); ++index) {
        const QString key = QString::fromUtf8(tractor->get_name(index));
        const char *value = tractor->get(key.toUtf8().constData());
        // MLT clear() leaves the name in its list with a null value. Undoing a
        // Look choice must expose the old marker again, not invent an empty pin.
        if (value && (key.startsWith(QLatin1String("letitedit_ai:")) || key.startsWith(QLatin1String("ai:"))))
            metadata[key] = QString::fromUtf8(value);
    }
    if (metadata.isEmpty())
        return {};
    static QHash<QByteArray, QPair<QString, qint64>> resolved;
    static QSet<QByteArray> pending;
    static QString personalRoot;
    const QByteArray key = QJsonDocument(metadata).toJson(QJsonDocument::Compact);
    const qint64 stamp = QFileInfo(personalRoot).lastModified().toMSecsSinceEpoch();
    if (resolved.contains(key) && resolved.value(key).second == stamp)
        return resolved.value(key).first;
    if (!pending.contains(key)) {
        pending.insert(key);
        QTimer::singleShot(0, window, [window, key, metadata]() {
            auto temporary = QSharedPointer<QTemporaryDir>::create();
            QFile file(temporary->filePath(QStringLiteral("request.json")));
            if (!temporary->isValid() || !file.open(QIODevice::WriteOnly)) {
                pending.remove(key);
                return;
            }
            file.write(QJsonDocument(QJsonObject{{"action", "project"}, {"project", metadata}}).toJson());
            file.close();
            auto process = new QProcess(window);
            QObject::connect(process, &QProcess::finished, window,
                             [process, temporary, key](int code, QProcess::ExitStatus) {
                const QJsonObject result = QJsonDocument::fromJson(process->readAllStandardOutput()).object();
                if (code == 0 && result.contains("id")) {
                    personalRoot = result.value("root").toString();
                    resolved.insert(key, {result.value("id").toString(), QFileInfo(personalRoot).lastModified().toMSecsSinceEpoch()});
                }
                pending.remove(key);
                process->deleteLater();
            });
            QObject::connect(process, &QProcess::errorOccurred, window, [process, key](QProcess::ProcessError) {
                pending.remove(key);
                process->deleteLater();
            });
            process->start(pythonExe(), {aiRootPath(QStringLiteral("bridge/look_library.py")),
                                        QStringLiteral("--request"), file.fileName()});
            QTimer::singleShot(30000, process, [process]() { process->kill(); });
        });
    }
    return resolved.value(key).first;
}

QUndoCommand *projectPropertiesCommand(const QJsonObject &properties, const QString &label)
{
    return new ProjectPropertiesCommand(properties, label);
}

void setProjectStyle(MainWindow *window, const QString &name)
{
    if (!window || !window->multitrack() || projectStyle(window) == name)
        return;
    window->undoStack()->push(new ProjectPropertiesCommand(
        QJsonObject{{kLookProperty, name.isEmpty() ? QJsonValue(QStringLiteral("neutral")) : QJsonValue(name)}},
        name.isEmpty() ? QObject::tr("Neutral Look for this video") : QObject::tr("Use the Look \"%1\" on this video").arg(name)));
}

QString save(MainWindow *window, const QString &rawName)
{
    QString name = safeName(rawName);
    if (name.isEmpty())
        return QObject::tr("Give the Look a name.");
    QMap<QString, QString> caption = window->subtitlesDock()->shownCaptionProperties();
    if (caption.value("size").toInt() <= 0)
        caption = SubtitlesDock::chosenCaptionProperties();
    const double w = MLT.profile().width(), h = MLT.profile().height(), shortSide = qMin(w, h);
    QVariantMap custom;
    for (const char *key : kCaptionKeys)
        custom[key] = caption.value(key);
    // Sizes as shares of the frame's height too, the way the AI's style packs scale them, so the app and the AI
    // make the same caption on a frame of any shape.
    QVariantMap heights;
    for (const char *key : kSizeKeys) {
        custom[key] = caption.value(key).toDouble() / shortSide;
        heights[key] = caption.value(key).toDouble() / h;
    }
    custom["heights"] = heights;
    custom["geometry"] = caption.value("geometry");
    custom["valign"] = caption.value("valign");
    custom["tall"] = w < h;
    const QVariantMap app{{"captions", custom},
                          {"pauses", leSettings().value("pauses/mode", "normal")},
                          {"fillers", leSettings().value("pauses/fillers", true)},
                          {"music_volume", leSettings().value("music/volume", 1)},
                          {"duck", leSettings().value("music/duck", true)},
                          {"words", leSettings().value("captions/words").toStringList()}};
    QJsonObject changes = lookChanges(custom, h, app);
    QJsonObject caps = changes.value("captions").toObject();
    const QJsonObject corrections = correctionsFrom(app.value("words").toStringList());
    if (!corrections.isEmpty())
        caps["corrections"] = corrections;
    changes["captions"] = caps;
    if (!personalLookExists(name)) {
        changes["label"] = name;
        changes["description"] = QStringLiteral("Saved in letitedit");
    }
    QString why;
    changes["app"] = QJsonObject::fromVariantMap(app);
    writeLook(name, changes, &why);
    if (!why.isEmpty())
        return QObject::tr("Could not save the Look: %1").arg(why);

    leSettings().setValue("looks/active", name);
    return QString();
}

QString apply(MainWindow *window, const QString &name)
{
    const QString title = lookTitle(name);
    const QVariantMap savedApp = appSettings(name).toVariantMap();
    QVariantMap style = fromPack(name);
    if (savedApp.contains("fillers"))
        style["fillers"] = savedApp.value("fillers");
    const QVariantMap pack = style;
    if (pack.isEmpty() && style.isEmpty())
        return QString();
    if (style.value("captions").toMap().isEmpty()) {
        // the pack's own settings (the AI's, or the panel's fields); the app's exact ones win where both exist
        for (auto it = pack.cbegin(); it != pack.cend(); ++it)
            if (!style.contains(it.key()) || it.key() == QLatin1String("captions"))
                style.insert(it.key(), it.value());
    }
    if (style.value("words").toStringList().isEmpty())
        style["words"] = pack.value("words"); // the pack's word list (set by the panel or the AI)
    const QVariantMap captions = style.value("captions").toMap();
    if (!captions.isEmpty()) {
        leSettings().setValue("captions/look", "style");
        leSettings().setValue("captions/custom", captions);
    }
    if (style.contains("pauses"))
        leSettings().setValue("pauses/mode", style.value("pauses"));
    if (style.contains("fillers"))
        leSettings().setValue("pauses/fillers", style.value("fillers"));
    if (style.contains("music_volume"))
        leSettings().setValue("music/volume", style.value("music_volume"));
    if (style.contains("duck"))
        leSettings().setValue("music/duck", style.value("duck"));
    if (!style.value("words").toStringList().isEmpty())
        leSettings().setValue("captions/words", style.value("words").toStringList());
    leSettings().setValue("looks/active", name);
    window->undoStack()->beginMacro(QObject::tr("Use my Look \"%1\"").arg(title));
    const bool restyled = !captions.isEmpty()
                          && window->subtitlesDock()->applyCaptionProperties(SubtitlesDock::chosenCaptionProperties());
    setProjectStyle(window, name);
    window->undoStack()->endMacro();
    if (captions.isEmpty())
        return QObject::tr("Using “%1” on this video: your AI follows it, and Remove pauses and Add music use it. It "
                           "has no caption look yet, so the captions stay as they are (Captions tab: Take the caption "
                           "look from this video).")
            .arg(title);
    return restyled ? QObject::tr("Using “%1” on this video: captions restyled, Remove pauses and Add music use it, and "
                                  "your AI follows it. Undo puts it all back.")
                          .arg(title)
                    : QObject::tr("Using “%1” on this video: new captions, Remove pauses and Add music use it, and your "
                                  "AI follows it.")
                          .arg(title);
}

namespace {

// One field of the panel (style_pack.MY_STYLE_FIELDS): its editor, and the value it was loaded with.
struct Field
{
    QString key;
    QString type;
    QStringList choices;
    QWidget *editor = nullptr;
    QJsonValue loaded;
    QJsonValue initial; // what the editor showed right after loading: a change is a difference from this
};

class MyStylePanel : public QDialog
{
public:
    explicit MyStylePanel(MainWindow *window)
        : QDialog(window)
        , m_window(window)
    {
        using namespace LetItEditColors;
        setObjectName(QStringLiteral("myStyleDialog"));
        setWindowTitle(tr("My Looks"));
        setMinimumSize(720, 600);
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(20, 16, 20, 14);
        column->setSpacing(10);
        auto intro = new QLabel(tr("Personal Looks hold how your videos look, sound and feel. Copy a Look or make one, "
                                   "then use it on a video or choose it in New video."), this);
        intro->setWordWrap(true);
        column->addWidget(intro);
        auto top = new QHBoxLayout;
        top->addWidget(new QLabel(tr("Look"), this));
        m_list = new QComboBox(this);
        m_list->setObjectName(QStringLiteral("myStyleList"));
        m_list->setMinimumWidth(220);
        top->addWidget(m_list);
        auto add = new QPushButton(tr("New Look..."), this);
        add->setObjectName(QStringLiteral("myStyleNew"));
        connect(add, &QPushButton::clicked, this, [this]() { newStyle(); });
        top->addWidget(add);
        // Import a style: a new style of the person's own, made from videos they like
        auto fromVideos = new QPushButton(tr("From videos I like..."), this);
        fromVideos->setObjectName(QStringLiteral("myStyleImport"));
        fromVideos->setToolTip(tr("Learn a reusable Look from one to three reference videos"));
        connect(fromVideos, &QPushButton::clicked, this, [this]() {
            if (!leaveDraft())
                return;
            LearnLooks::showDialog(m_window);
            for (const auto &item : personalLooks()) {
                const auto card = item.toObject();
                const QString id = card.value("id").toString();
                if (m_list->findData(id) < 0)
                    m_list->addItem(card.value("label").toString(id), id);
            }
        });
        top->addWidget(fromVideos);
        auto copy = new QPushButton(tr("Copy a Look..."), this);
        copy->setObjectName(QStringLiteral("myLookCopy"));
        connect(copy, &QPushButton::clicked, this, [this]() {
            if (!leaveDraft())
                return;
            const auto cards = lookRequest({{"action", "list"}}).value("looks").toArray();
            QStringList labels;
            for (const auto &item : cards) {
                const QString title = item.toObject().value("label").toString();
                QString label = title;
                for (int suffix = 2; labels.contains(label); ++suffix)
                    label = title + QStringLiteral(" (%1)").arg(suffix);
                labels << label;
            }
            QInputDialog ask(this);
            ask.setObjectName(QStringLiteral("myLookCopyDialog"));
            ask.setWindowTitle(tr("Copy a Look"));
            ask.setLabelText(tr("Look to copy"));
            ask.setComboBoxItems(labels);
            ask.setComboBoxEditable(false);
            if (auto choice = ask.findChild<QComboBox *>())
                choice->setObjectName(QStringLiteral("myLookCopyChoice"));
            if (ask.exec() != QDialog::Accepted || ask.textValue().isEmpty())
                return;
            const QString label = ask.textValue();
            const auto card = cards.at(labels.indexOf(label)).toObject();
            QString why;
            const auto saved = lookRequest({{"action", "copy"}, {"identity", card.value("id")}}, &why);
            if (saved.isEmpty()) {
                m_status->setText(tr("Couldn't copy: %1").arg(why));
                return;
            }
            const QString id = saved.value("id").toString();
            m_list->addItem(saved.value("title").toString(card.value("label").toString(id)), id);
            m_list->setCurrentIndex(m_list->findData(id));
        });
        top->addWidget(copy);
        top->addStretch(1);
        m_inUse = new QLabel(this);
        m_inUse->setObjectName(QStringLiteral("myStyleInUse"));
        m_inUse->setProperty("studioMuted", true);
        top->addWidget(m_inUse);
        column->addLayout(top);
        m_tabs = new QTabWidget(this);
        m_tabs->setObjectName(QStringLiteral("myStyleTabs"));
        column->addWidget(m_tabs, 1);
        m_status = new QLabel(this);
        m_status->setObjectName(QStringLiteral("myStyleStatus"));
        m_status->setWordWrap(true);
        m_status->setStyleSheet(QStringLiteral("color: %1;").arg(tealLight));
        column->addWidget(m_status);
        auto buttons = new QHBoxLayout;
        auto close = new QPushButton(tr("Close"), this);
        close->setObjectName(QStringLiteral("myStyleClose"));
        connect(close, &QPushButton::clicked, this, &QDialog::reject); // reject() asks first when there are changes
        buttons->addWidget(close);
        buttons->addStretch(1);
        m_save = new QPushButton(tr("Save"), this);
        m_save->setObjectName(QStringLiteral("myStyleSave"));
        m_save->setToolTip(tr("Save a new Look revision; other settings stay as they are"));
        connect(m_save, &QPushButton::clicked, this, [this]() { saveFields(true); });
        buttons->addWidget(m_save);
        m_use = new QPushButton(tr("Use on this video"), this);
        m_use->setObjectName(QStringLiteral("myStyleUse"));
        m_use->setProperty("studioPrimary", true);
        m_use->setToolTip(tr("Saves, then restyles the captions, sets Remove pauses and Add music, and tells your AI to "
                             "follow this Look on this video (one Undo step)"));
        connect(m_use, &QPushButton::clicked, this, [this]() { use(); });
        buttons->addWidget(m_use);
        column->addLayout(buttons);

        const QString inUse = projectStyle(window);
        for (const auto &item : personalLooks()) {
            const auto card = item.toObject();
            m_list->addItem(card.value("label").toString(), card.value("id").toString());
        }
        if (!m_list->count())
            m_list->addItem(tr("My Look"), tr("My Look"));
        const int start = m_list->findData(m_list->findData(inUse) >= 0 ? inUse : active());
        m_list->setCurrentIndex(qMax(0, start));
        connect(m_list, &QComboBox::currentIndexChanged, this, [this]() {
            const QString next = m_list->currentData().toString();
            if (next == m_name)
                return;
            // another style: what was typed in this one is saved, let go, or kept (and this one stays)
            if (!leaveDraft()) {
                const QSignalBlocker block(m_list);
                m_list->setCurrentIndex(qMax(0, m_list->findData(m_name)));
                return;
            }
            // a name from New style... that was never saved and was left: not a style
            for (int i = m_list->count() - 1; i >= 0; --i) {
                const QString name = m_list->itemData(i).toString();
                if (name != next && name == m_unsavedNew && !QFileInfo::exists(folder() + QLatin1Char('/') + name)) {
                    const QSignalBlocker block(m_list);
                    m_list->removeItem(i);
                }
            }
            load(next);
        });
        load(m_list->currentData().toString());
    }

    // Close, Escape and the window's own close button all come here: changes not saved yet are never lost without
    // asking.
    void reject() override
    {
        if (!leaveDraft())
            return;
        QDialog::reject();
    }

    // Checks: the list's choice, as a click would make it.
    void qaSelect(const QString &name)
    {
        const int i = m_list->findData(name);
        if (i >= 0)
            m_list->setCurrentIndex(i);
    }

    // The panel's state for checks: the style shown, whether it has changes not saved, and the status line.
    QJsonObject qaState()
    {
        QJsonArray changed;
        for (const auto &f : std::as_const(m_fields))
            if (!same(current(f), f.initial))
                changed.append(f.key);
        return QJsonObject{{"style", m_name}, {"look", m_name}, {"revision", m_revision},
                           {"fix_words", QJsonArray::fromStringList(leSettings().value("captions/words").toStringList())},
                           {"dirty", dirty()}, {"status", m_status->text()}, {"visible", isVisible()},
                           {"changed", changed}};
    }

private:
    // Before the draft goes (closing, or another style): Save, Discard or Cancel when something changed. True: go on
    // (saved, discarded or nothing to save). A save that fails keeps the draft and the panel as they are.
    bool leaveDraft()
    {
        if (!dirty())
            return true;
        QMessageBox ask(QMessageBox::Question, tr("My Looks"),
                        tr("You changed “%1” and haven't saved it yet.").arg(m_style.value("label").toString(m_name)),
                        QMessageBox::NoButton, this);
        ask.setObjectName(QStringLiteral("myStyleUnsavedDialog"));
        ask.setInformativeText(tr("Save your changes before you go on?"));
        auto save = ask.addButton(tr("Save"), QMessageBox::AcceptRole);
        auto discard = ask.addButton(tr("Discard"), QMessageBox::DestructiveRole);
        auto cancel = ask.addButton(tr("Cancel"), QMessageBox::RejectRole);
        save->setObjectName(QStringLiteral("myStyleAskSave"));
        discard->setObjectName(QStringLiteral("myStyleAskDiscard"));
        cancel->setObjectName(QStringLiteral("myStyleAskCancel"));
        ask.setDefaultButton(save);
        ask.setEscapeButton(cancel);
        ask.exec();
        if (ask.clickedButton() == discard)
            return true;
        if (ask.clickedButton() != save)
            return false; // Cancel (or the box closed): stay, with everything as typed
        if (saveFields(true))
            return true;
        // the save failed: the draft stays in the panel, and the status line says why
        return false;
    }

    void load(const QString &name)
    {
        m_name = name;
        m_words = nullptr; // the tabs holding these are rebuilt below
        m_volume = nullptr;
        m_duck = nullptr;
        const bool exists = personalLookExists(name);
        QString why;
        const QJsonObject read = lookRequest({{"action", "editor"}, {"identity", exists ? name : QStringLiteral("neutral")}}, &why);
        m_revision = read.value("revision").toString();
        m_pendingAssets = {};
        m_fields.clear();
        while (m_tabs->count()) {
            auto w = m_tabs->widget(0);
            m_tabs->removeTab(0);
            w->deleteLater();
        }
        m_inUse->setText(projectStyle(m_window) == name ? tr("In use on this video") : QString());
        if (read.isEmpty()) {
            m_status->setText(tr("Couldn't read the Look: %1").arg(why));
            m_save->setEnabled(false);
            m_use->setEnabled(false);
            return;
        }
        m_save->setEnabled(true);
        m_use->setEnabled(true);
        m_style = read.value("style").toObject();
        if (!exists)
            m_style["label"] = name;
        QMap<QString, QFormLayout *> groups;
        QStringList order;
        const auto tab = [&](const QString &group) {
            if (!groups.contains(group)) {
                auto scroll = new QScrollArea(m_tabs);
                scroll->setWidgetResizable(true);
                scroll->setFrameShape(QFrame::NoFrame);
                auto body = new QWidget(scroll);
                auto form = new QFormLayout(body);
                form->setContentsMargins(14, 14, 14, 14);
                form->setVerticalSpacing(10);
                form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
                scroll->setWidget(body);
                m_tabs->addTab(scroll, displayGroup(group));
                groups.insert(group, form);
                order << group;
            }
            return groups.value(group);
        };
        bool captionsDone = false;
        for (const auto &v : read.value("fields").toArray()) {
            QJsonObject f = v.toObject();
            if (!exists && f.value("key").toString() == QLatin1String("label"))
                f["value"] = name;
            const QString group = f.value("group").toString(QStringLiteral("More"));
            if (group != QLatin1String("About") && !captionsDone) {
                captionsTab(tab(QStringLiteral("Captions")), name, exists);
                soundRows(tab(QStringLiteral("Pacing")));
                captionsDone = true;
            }
            addField(tab(group), f);
        }
        if (!captionsDone)
            captionsTab(tab(QStringLiteral("Captions")), name, exists);
        for (auto &f : m_fields)
            f.initial = current(f);
        m_status->setText(exists ? QString() : tr("A new Look: press Save to keep it."));
    }

    static QString displayGroup(const QString &group)
    {
        static const QMap<QString, QString> names{{QStringLiteral("About"), QObject::tr("About")},
                                                  {QStringLiteral("Captions"), QObject::tr("Captions")},
                                                  {QStringLiteral("Pacing"), QObject::tr("Pace and sound")},
                                                  {QStringLiteral("B-roll"), QObject::tr("B-roll")},
                                                  {QStringLiteral("Shots"), QObject::tr("Shots")},
                                                  {QStringLiteral("Music"), QObject::tr("Music")},
                                                  {QStringLiteral("Signature"), QObject::tr("Signature")},
                                                  {QStringLiteral("Pop-ups"), QObject::tr("Pop-ups")}};
        return names.value(group, group);
    }

    static QJsonValue valueAt(const QJsonObject &style, const QString &key)
    {
        QJsonValue cur = style;
        for (const auto &part : key.split(QLatin1Char('.'))) {
            if (!cur.isObject() || !cur.toObject().contains(part))
                return QJsonValue();
            cur = cur.toObject().value(part);
        }
        return cur;
    }

    void addField(QFormLayout *form, const QJsonObject &f)
    {
        Field field;
        field.key = f.value("key").toString();
        field.type = f.value("type").toString(QStringLiteral("text"));
        field.loaded = f.value("value");
        const QString label = f.value("label").toString(field.key);
        const QString help = f.value("help").toString();
        const QString objectName = QStringLiteral("myStyle_") + QString(field.key).replace(QLatin1Char('.'), QLatin1Char('_'));
        if (field.type == QLatin1String("choice")) {
            auto combo = new QComboBox;
            const QJsonArray choices = f.value("choices").toArray();
            const QJsonArray labels = f.value("choice_labels").toArray();
            for (int i = 0; i < choices.size(); ++i) {
                const QString value = choices[i].toVariant().toString();
                QString text = i < labels.size() ? labels[i].toString() : value;
                if (!text.isEmpty())
                    text[0] = text[0].toUpper();
                combo->addItem(text, value);
                field.choices << value;
            }
            const int at = combo->findData(field.loaded.toVariant().toString());
            if (at >= 0)
                combo->setCurrentIndex(at);
            else if (!field.loaded.isNull() && !field.loaded.isUndefined()) {
                combo->addItem(field.loaded.toVariant().toString(), field.loaded.toVariant().toString());
                combo->setCurrentIndex(combo->count() - 1);
            }
            field.editor = combo;
        } else if (field.type == QLatin1String("number")) {
            auto spin = new QDoubleSpinBox;
            spin->setRange(f.value("min").toDouble(0.0), f.value("max").toDouble(1000.0));
            spin->setDecimals(2);
            spin->setSingleStep(0.05);
            spin->setValue(field.loaded.toDouble());
            field.editor = spin;
        } else if (field.type == QLatin1String("bool")) {
            auto box = new QCheckBox;
            box->setChecked(field.loaded.toBool());
            field.editor = box;
        } else if (field.type == QLatin1String("list")) {
            auto edit = new QPlainTextEdit;
            QStringList lines;
            for (const auto &item : field.loaded.toArray())
                lines << item.toVariant().toString();
            edit->setPlainText(lines.join(QLatin1Char('\n')));
            edit->setPlaceholderText(help.isEmpty() ? tr("One per line") : tr("One per line, %1").arg(help));
            edit->setFixedHeight(84);
            field.editor = edit;
        } else if (field.type == QLatin1String("file")) {
            auto holder = new QWidget;
            auto row = new QHBoxLayout(holder);
            row->setContentsMargins(0, 0, 0, 0);
            auto edit = new QLineEdit(field.loaded.isString() ? field.loaded.toString() : QString(), holder);
            edit->setObjectName(objectName + QStringLiteral("_path"));
            edit->setPlaceholderText(tr("None"));
            auto choose = new QPushButton(tr("Choose..."), holder);
            connect(choose, &QPushButton::clicked, this, [this, edit]() {
                const QString f = QFileDialog::getOpenFileName(this, tr("Choose a file"), edit->text(),
                                                               tr("Sounds (*.wav *.mp3 *.m4a *.flac *.aac *.ogg);;All files (*)"));
                if (!f.isEmpty())
                    edit->setText(QDir::toNativeSeparators(f));
            });
            row->addWidget(edit, 1);
            row->addWidget(choose);
            field.editor = holder;
        } else if (field.type == QLatin1String("popups")) {
            field.editor = popupTable(field.loaded.toArray());
            auto box = new QWidget;
            auto inside = new QVBoxLayout(box);
            inside->setContentsMargins(0, 0, 0, 0);
            auto lead = new QLabel(tr("When you say a word, a picture pops up on the video (your logo when you say your "
                                      "channel's name, say). Use your own pictures only."),
                                   box);
            lead->setWordWrap(true);
            lead->setProperty("studioMuted", true);
            inside->addWidget(lead);
            inside->addWidget(field.editor);
            auto rowButtons = new QHBoxLayout;
            auto addRow = new QPushButton(tr("Add a pop-up"), box);
            addRow->setObjectName(QStringLiteral("myStylePopupAdd"));
            auto table = static_cast<QTableWidget *>(field.editor);
            connect(addRow, &QPushButton::clicked, this, [this, table]() { addPopupRow(table, QJsonObject()); });
            auto removeRow = new QPushButton(tr("Remove"), box);
            connect(removeRow, &QPushButton::clicked, this, [table]() {
                if (table->currentRow() >= 0)
                    table->removeRow(table->currentRow());
            });
            rowButtons->addWidget(addRow);
            rowButtons->addWidget(removeRow);
            rowButtons->addStretch(1);
            inside->addLayout(rowButtons);
            field.editor->setObjectName(objectName);
            form->addRow(box);
            m_fields << field;
            return;
        } else {
            const bool long_ = field.key.endsWith(QLatin1String("notes")) || field.key == QLatin1String("taste")
                               || field.key.endsWith(QLatin1String("favorites"));
            if (long_) {
                auto edit = new QPlainTextEdit(field.loaded.toVariant().toString());
                edit->setFixedHeight(64);
                if (!help.isEmpty())
                    edit->setPlaceholderText(help);
                field.editor = edit;
            } else {
                auto edit = new QLineEdit(field.loaded.isNull() ? QString() : field.loaded.toVariant().toString());
                if (!help.isEmpty())
                    edit->setPlaceholderText(help);
                field.editor = edit;
            }
        }
        field.editor->setObjectName(objectName);
        field.editor->setAccessibleName(label);
        if (!help.isEmpty())
            field.editor->setToolTip(help);
        form->addRow(label, field.editor);
        m_fields << field;
    }

    QTableWidget *popupTable(const QJsonArray &entries)
    {
        auto table = new QTableWidget(0, 3);
        table->setHorizontalHeaderLabels({tr("When I say"), tr("Show this picture"), tr("Where")});
        table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
        table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
        table->horizontalHeader()->setSectionResizeMode(2, QHeaderView::ResizeToContents);
        table->verticalHeader()->hide();
        table->setMinimumHeight(150);
        for (const auto &e : entries)
            addPopupRow(table, e.toObject());
        return table;
    }

    void addPopupRow(QTableWidget *table, const QJsonObject &entry)
    {
        const int row = table->rowCount();
        table->insertRow(row);
        QStringList words;
        for (const auto &w : entry.value("words").toArray())
            words << w.toString();
        auto said = new QTableWidgetItem(words.join(QStringLiteral(", ")));
        said->setToolTip(tr("Words or names, separated by commas"));
        said->setData(Qt::UserRole, entry); // the rest of the entry (size, sound, timing) is kept as it was
        table->setItem(row, 0, said);
        const QString image = entry.value("asset").toObject().value("image").toString();
        auto holder = new QWidget(table);
        auto line = new QHBoxLayout(holder);
        line->setContentsMargins(2, 0, 2, 0);
        auto path = new QLineEdit(image, holder);
        const QJsonObject asset = entry.value("asset").toObject();
        const QString other = asset.contains("emoji") ? asset.value("emoji").toString()
                              : asset.contains("text") ? asset.value("text").toString()
                              : asset.contains("graphic") ? tr("a graphic")
                              : asset.contains("motion") ? tr("an animation") : QString();
        path->setPlaceholderText(other.isEmpty() ? tr("A picture file") : tr("Shows %1 (choose a picture to change it)").arg(other));
        auto choose = new QPushButton(tr("..."), holder);
        choose->setToolTip(tr("Choose a picture"));
        connect(choose, &QPushButton::clicked, this, [this, path]() {
            const QString f = QFileDialog::getOpenFileName(this, tr("Choose a picture"), path->text(),
                                                           tr("Pictures (*.png *.jpg *.jpeg *.webp *.svg)"));
            if (!f.isEmpty())
                path->setText(QDir::toNativeSeparators(f));
        });
        line->addWidget(path, 1);
        line->addWidget(choose);
        table->setCellWidget(row, 1, holder);
        auto where = new QComboBox(table);
        const QList<QPair<QString, QString>> places{{QStringLiteral("upper_right"), tr("Top right")},
                                                    {QStringLiteral("upper_left"), tr("Top left")},
                                                    {QStringLiteral("top"), tr("Top")},
                                                    {QStringLiteral("center"), tr("Middle")},
                                                    {QStringLiteral("lower_right"), tr("Bottom right")},
                                                    {QStringLiteral("lower_left"), tr("Bottom left")}};
        for (const auto &p : places)
            where->addItem(p.second, p.first);
        const int at = where->findData(entry.value("position").toString(QStringLiteral("upper_right")));
        where->setCurrentIndex(qMax(0, at));
        table->setCellWidget(row, 2, where);
    }

    // The pop-up rows as popups.entries; a picture from outside the style is copied into its assets folder (credited
    // as the person's own), so the style works on another PC too.
    QJsonArray popupEntries(QTableWidget *table, bool copyPictures, QStringList *credits)
    {
        QJsonArray out;

        for (int r = 0; r < table->rowCount(); ++r) {
            const auto item = table->item(r, 0);
            QStringList words;
            for (const auto &w : (item ? item->text() : QString()).split(QLatin1Char(','), Qt::SkipEmptyParts))
                if (!w.trimmed().isEmpty())
                    words << w.trimmed();
            auto path = table->cellWidget(r, 1) ? table->cellWidget(r, 1)->findChild<QLineEdit *>() : nullptr;
            QString image = path ? path->text().trimmed() : QString();
            QJsonObject entry = item ? item->data(Qt::UserRole).toJsonObject() : QJsonObject();
            const QJsonObject oldAsset = entry.value("asset").toObject();
            const bool otherAsset = !oldAsset.isEmpty() && !oldAsset.contains("image");
            if (words.isEmpty() || (image.isEmpty() && !otherAsset))
                continue;
            if (image.isEmpty()) { // an emoji, text or graphic pop-up the AI made: kept, with the words as typed
                QJsonArray w;
                for (const auto &word : words)
                    w.append(word);
                entry["words"] = w;
                if (auto where = qobject_cast<QComboBox *>(table->cellWidget(r, 2)))
                    entry["position"] = where->currentData().toString();
                out.append(entry);
                continue;
            }
            if (copyPictures && QFileInfo(image).isAbsolute()) {
                const QString rel = QStringLiteral("assets/") + QUuid::createUuid().toString(QUuid::WithoutBraces)
                                    + QLatin1Char('-') + QFileInfo(image).fileName();
                m_pendingAssets[rel] = image;
                image = rel;
                if (credits)
                    *credits << rel;
            }
            QJsonArray w;
            for (const auto &word : words)
                w.append(word);
            entry["words"] = w;
            QJsonObject asset = entry.value("asset").toObject();
            asset.remove("emoji");
            asset.remove("text");
            asset["image"] = QDir::fromNativeSeparators(image);
            entry["asset"] = asset;
            if (auto where = qobject_cast<QComboBox *>(table->cellWidget(r, 2)))
                entry["position"] = where->currentData().toString();
            if (!entry.contains("id"))
                entry["id"] = words.first().toLower().remove(QRegularExpression(QStringLiteral("[^a-z0-9]+")));
            out.append(entry);
        }
        return out;
    }

    // The caption look taken from this video, and the words captions should spell your way.
    void captionsTab(QFormLayout *form, const QString &name, bool exists)
    {
        auto look = new QLabel(this);
        look->setObjectName(QStringLiteral("myStyleLook"));
        look->setWordWrap(true);
        const QJsonObject caps = m_style.value("captions").toObject();
        const QJsonObject font = m_style.value("fonts").toObject().value("captions").toObject();
        look->setText(exists ? tr("Captions in %1 %2, size %3.")
                                   .arg(font.value("family").toString(tr("the usual font")))
                                   .arg(font.value("weight").toInt() >= 700 ? tr("bold") : QString())
                                   .arg(caps.value("size").toInt())
                             : tr("No caption look saved yet."));
        form->addRow(tr("Caption look"), look);
        auto take = new QPushButton(tr("Take the caption look from this video"), this);
        take->setObjectName(QStringLiteral("myStyleTakeLook"));
        take->setToolTip(tr("The caption look, music volume and pause length become a new Look revision"));
        connect(take, &QPushButton::clicked, this, [this, name]() {
            const QString problem = save(m_window, name);
            if (!problem.isEmpty()) {
                m_status->setText(problem);
                return;
            }
            const QString keep = active();
            const int index = m_list->findData(name);
            if (index >= 0) {
                const QSignalBlocker block(m_list);
                m_list->setItemData(index, keep);
            }
            load(keep);
            m_status->setText(tr("Saved this video's caption look into “%1”.").arg(keep));
        });
        form->addRow(QString(), take);
        m_words = new QTableWidget(0, 2, this);
        m_words->setObjectName(QStringLiteral("myStyleWords"));
        m_words->setHorizontalHeaderLabels({tr("When it sounds like"), tr("Write it as")});
        m_words->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
        m_words->verticalHeader()->hide();
        m_words->setMinimumHeight(140);
        const QJsonObject corrections = caps.value("corrections").toObject();
        QStringList rows;
        for (auto it = corrections.begin(); it != corrections.end(); ++it)
            rows << it.key() + QLatin1Char('\t') + it.value().toString();
        if (rows.isEmpty()) // words saved by older versions sit in letitedit.json
            rows = m_style.value("app").toObject().value("words").toVariant().toStringList();
        m_loadedWords = rows;
        for (const auto &row : rows) {
            const int tab = row.indexOf(QLatin1Char('\t'));
            if (tab <= 0)
                continue;
            const int r = m_words->rowCount();
            m_words->insertRow(r);
            m_words->setItem(r, 0, new QTableWidgetItem(row.left(tab)));
            m_words->setItem(r, 1, new QTableWidgetItem(row.mid(tab + 1)));
        }
        auto box = new QWidget(this);
        auto inside = new QVBoxLayout(box);
        inside->setContentsMargins(0, 0, 0, 0);
        inside->addWidget(m_words);
        auto addWord = new QPushButton(tr("Add a word"), box);
        addWord->setObjectName(QStringLiteral("myStyleWordAdd"));
        connect(addWord, &QPushButton::clicked, this, [this]() {
            m_words->insertRow(m_words->rowCount());
            m_words->setCurrentCell(m_words->rowCount() - 1, 0);
            m_words->editItem(m_words->item(m_words->rowCount() - 1, 0));
        });
        inside->addWidget(addWord, 0, Qt::AlignLeft);
        form->addRow(tr("Words captions should\nspell your way"), box);
    }

    // Music under the talking and its dip, the app's own two sound settings, in pack terms.
    void soundRows(QFormLayout *form)
    {
        m_volume = new QComboBox(this);
        m_volume->setObjectName(QStringLiteral("myStyleMusicVolume"));
        m_volume->addItem(tr("Quieter"), -22.0);
        m_volume->addItem(tr("Normal"), -18.0);
        m_volume->addItem(tr("Louder"), -14.0);
        const double talk = valueAt(m_style, QStringLiteral("music.zones.talk")).toDouble(-18.0);
        m_volume->setCurrentIndex(talk <= -20.0 ? 0 : talk >= -16.0 ? 2 : 1);
        m_loadedVolume = m_volume->currentIndex();
        form->addRow(tr("Music under talking"), m_volume);
        m_duck = new QCheckBox(tr("Lower the music while someone talks"), this);
        m_duck->setObjectName(QStringLiteral("myStyleDuck"));
        m_duck->setChecked(valueAt(m_style, QStringLiteral("music.duck_under_speech")).toBool(true));
        m_loadedDuck = m_duck->isChecked();
        form->addRow(QString(), m_duck);
    }

    QJsonValue current(const Field &f, bool copyPictures = false, QStringList *credits = nullptr)
    {
        if (auto combo = qobject_cast<QComboBox *>(f.editor)) {
            const QString v = combo->currentData().toString();
            // numbers stay numbers ("1-3" and the like stay words)
            bool isNumber = false;
            const double n = v.toDouble(&isNumber);
            return f.loaded.isDouble() && isNumber ? QJsonValue(n) : QJsonValue(v);
        }
        if (auto spin = qobject_cast<QDoubleSpinBox *>(f.editor))
            return std::round(spin->value() * 100) / 100;
        if (auto box = qobject_cast<QCheckBox *>(f.editor))
            return box->isChecked();
        if (auto table = qobject_cast<QTableWidget *>(f.editor))
            return popupEntries(table, copyPictures, credits);
        if (auto edit = qobject_cast<QPlainTextEdit *>(f.editor)) {
            if (f.type == QLatin1String("list")) {
                QJsonArray out;
                for (const auto &line : edit->toPlainText().split(QLatin1Char('\n'), Qt::SkipEmptyParts))
                    if (!line.trimmed().isEmpty())
                        out.append(line.trimmed());
                return out;
            }
            return edit->toPlainText().trimmed();
        }
        if (auto edit = qobject_cast<QLineEdit *>(f.editor))
            return edit->text().trimmed();
        if (auto path = f.editor ? f.editor->findChild<QLineEdit *>() : nullptr) {
            const QString p = QDir::fromNativeSeparators(path->text().trimmed());
            return p.isEmpty() ? QJsonValue(QJsonValue::Null) : QJsonValue(p);
        }
        return QJsonValue();
    }

    static bool same(const QJsonValue &a, const QJsonValue &b)
    {
        const auto norm = [](const QJsonValue &v) {
            if (v.isNull() || v.isUndefined())
                return QJsonValue(QString());
            return v;
        };
        return norm(a) == norm(b);
    }

    QStringList wordRows() const
    {
        QStringList rows;
        if (!m_words)
            return rows;
        for (int r = 0; r < m_words->rowCount(); ++r) {
            const QString heard = m_words->item(r, 0) ? m_words->item(r, 0)->text().trimmed() : QString();
            const QString written = m_words->item(r, 1) ? m_words->item(r, 1)->text().trimmed() : QString();
            if (!heard.isEmpty() && !written.isEmpty())
                rows << heard + QLatin1Char('\t') + written;
        }
        return rows;
    }

    bool dirty()
    {
        for (const auto &f : std::as_const(m_fields))
            if (!same(current(f), f.initial))
                return true;
        return wordRows() != m_loadedWords || (m_volume && m_volume->currentIndex() != m_loadedVolume)
               || (m_duck && m_duck->isChecked() != m_loadedDuck);
    }

    static void put(QJsonObject &into, const QString &key, const QJsonValue &value)
    {
        const int dot = key.indexOf(QLatin1Char('.'));
        if (dot < 0) {
            into[key] = value;
            return;
        }
        QJsonObject child = into.value(key.left(dot)).toObject();
        put(child, key.mid(dot + 1), value);
        into[key.left(dot)] = child;
    }

    // Only what changed goes in, merged by style_pack.update(): what the AI or another window set stays.
    bool saveFields(bool report)
    {
        const bool isNew = !personalLookExists(m_name);
        m_pendingAssets = {};
        QJsonObject changes;
        QStringList credits;
        for (const auto &f : std::as_const(m_fields)) {
            if (isNew || !same(current(f), f.initial))
                put(changes, f.key, current(f, true, &credits));
        }
        const QStringList rows = wordRows();
        if (isNew || rows != m_loadedWords) {
            put(changes, QStringLiteral("captions.corrections"), correctionsFrom(rows));

        }
        QJsonObject app;
        if (m_volume && (isNew || m_volume->currentIndex() != m_loadedVolume)) {
            const double talk = m_volume->currentData().toDouble();
            put(changes, QStringLiteral("music.zones.talk"), talk);
            put(changes, QStringLiteral("music.zones.montage"), talk <= -20.0 ? -10.0 : talk >= -16.0 ? -3.0 : -6.0);
            app["music_volume"] = m_volume->currentIndex();
        }
        if (m_duck && (isNew || m_duck->isChecked() != m_loadedDuck)) {
            put(changes, QStringLiteral("music.duck_under_speech"), m_duck->isChecked());
            app["duck"] = m_duck->isChecked();
        }
        for (const auto &f : std::as_const(m_fields))
            if (f.key == QLatin1String("editing.max_pause") && (isNew || !same(current(f), f.initial))) {
                const double pause = current(f).toDouble();
                app["pauses"] = pause >= 0.5 ? "gentle" : pause < 0.28 ? "tight" : "normal";
            }
        if (!credits.isEmpty()) {
            QJsonArray list = m_style.value("credits").toArray();
            for (const auto &file : credits) {
                bool listed = false;
                for (const auto &c : list)
                    listed |= c.toObject().value("file").toString() == file;
                if (!listed)
                    list.append(QJsonObject{{"file", file}, {"source", "my own picture"}, {"licence", "own work"}});
            }
            changes["credits"] = list;
        }
        if (isNew && !changes.contains("label"))
            changes["label"] = m_name;
        if (changes.isEmpty()) {
            if (report)
                m_status->setText(tr("Nothing changed."));
            return true;
        }
        if (isNew || rows != m_loadedWords)
            app["words"] = QJsonArray::fromStringList(rows);
        if (!app.isEmpty())
            changes["app"] = app;
        QString why;
        const QString previousId = m_name;
        // QA: LETITEDIT_QA_STYLE_SAVE_FAIL=<file>: saving fails while that file exists (a check sees the draft kept)
        const QString qaFail = qEnvironmentVariable("LETITEDIT_QA_STYLE_SAVE_FAIL");
        const QStringList problems = !qaFail.isEmpty() && QFileInfo::exists(qaFail)
                                         ? (why = QStringLiteral("the disk said no (a test)"), QStringList())
                                         : writeLook(m_name, changes, &why, m_pendingAssets);
        if (!why.isEmpty()) {
            m_status->setText(tr("Couldn't save: %1. Your changes are still here.").arg(why));
            return false;
        }
        const int index = m_list->findData(previousId);
        if (index >= 0) {
            const QSignalBlocker block(m_list);
            m_list->setItemData(index, m_name);
            m_list->setItemText(index, changes.value("label").toString(m_list->itemText(index)));
        }
        if (active() == previousId)
            leSettings().setValue("looks/active", m_name);
        leSettings().setValue("captions/words", rows);
        const QString keep = m_name;
        load(keep);
        const QString title = m_style.value("label").toString(m_list->currentText());
        if (report || !problems.isEmpty())
            m_status->setText(problems.isEmpty() ? tr("Saved “%1”.").arg(title)
                                                 : tr("Saved “%1”. Worth a look: %2").arg(title, problems.mid(0, 3).join(QStringLiteral("; "))));
        return true;
    }

    void use()
    {
        if (dirty() || !personalLookExists(m_name)) {
            if (!saveFields(false))
                return;
        }
        const QString line = apply(m_window, m_name);
        m_status->setText(line.isEmpty() ? tr("That Look could not be read.") : line);
        if (!line.isEmpty())
            m_window->showStatusMessage(line, 12);
        m_inUse->setText(projectStyle(m_window) == m_name ? tr("In use on this video") : QString());
    }

    void newStyle()
    {
        bool ok = false;
        const QString name = safeName(QInputDialog::getText(this,
                                                            tr("New Look"),
                                                            tr("Name for the Look:"),
                                                            QLineEdit::Normal,
                                                            QString(),
                                                            &ok));
        if (!ok || name.isEmpty())
            return;
        if (m_list->findData(name) < 0) {
            m_list->addItem(name, name);
            m_unsavedNew = name;
        }
        m_list->setCurrentIndex(m_list->findData(name));
    }

    MainWindow *m_window;
    QComboBox *m_list = nullptr;
    QLabel *m_inUse = nullptr;
    QTabWidget *m_tabs = nullptr;
    QLabel *m_status = nullptr;
    QPushButton *m_save = nullptr;
    QPushButton *m_use = nullptr;
    QString m_name;
    QString m_revision;
    QJsonObject m_pendingAssets;
    QJsonObject m_style;
    QList<Field> m_fields;
    QTableWidget *m_words = nullptr;
    QStringList m_loadedWords;
    QComboBox *m_volume = nullptr;
    int m_loadedVolume = 1;
    QCheckBox *m_duck = nullptr;
    bool m_loadedDuck = true;
    QString m_unsavedNew; // a name from New style... not saved yet
};

} // namespace

QPointer<QDialog> &openPanel()
{
    static QPointer<QDialog> panel;
    return panel;
}

void show(MainWindow *window)
{
    MyStylePanel panel(window);
    openPanel() = &panel;
    panel.exec();
}

QJsonObject panelState()
{
    if (auto panel = static_cast<MyStylePanel *>(openPanel().data()))
        return panel->qaState();
    return QJsonObject{{"visible", false}};
}

void selectInPanel(const QString &name)
{
    if (auto panel = static_cast<MyStylePanel *>(openPanel().data()))
        QMetaObject::invokeMethod(panel, [panel, name]() { panel->qaSelect(name); }, Qt::QueuedConnection);
}

} // namespace MyStyle
