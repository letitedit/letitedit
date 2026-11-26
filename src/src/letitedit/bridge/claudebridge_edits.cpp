/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The bridge's edits as one Undo step each: a section deleted across tracks, captions edited, tracks replaced, a whole edit transaction, and the window's collaboration notices.
 * (Split out of claudebridge.cpp; ClaudeBridge is declared in claudebridge.h.)
 */
#include "letitedit/bridge/claudebridge.h"
#include "letitedit/bridge/bridgehelpers.h"
#include "letitedit/panels/musicpicker.h"
#include "letitedit/export/othersizes.h"
#include "letitedit/export/exportchecks.h"
#include "letitedit/airoot.h"
#include "letitedit/panels/aiaudiolibrary.h"
#include "letitedit/bridge/aicollaboration.h"
#include "letitedit/panels/hookpanel.h"
#include "letitedit/panels/myassets.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/review/reviewmode.h"
#include "letitedit/dialogs/lefeatures.h"
#include "jobqueue.h"
#include "jobs/abstractjob.h"
#include "letitedit/chat/aichatpanel.h"
#include "models/subtitlesselectionmodel.h"
#include "settings.h"
#include <QStandardPaths>
#include <QCryptographicHash>
#include <QLineEdit>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QFormLayout>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QComboBox>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QTabWidget>
#include <QDialogButtonBox>
#include <QMenuBar>
#include <QDateTime>
#include <QPixmap>
#include <QWindow>
#include <qpa/qwindowsysteminterface.h>

#include "Logger.h"
#include "actions.h"
#include "commands/timelinecommands.h"
#include "commands/subtitlecommands.h"
#include "controllers/filtercontroller.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "qmltypes/qmlutilities.h"
#include "videowidget.h"
#include "mltcontroller.h"
#include "player.h"
#include "models/markersmodel.h"
#include "models/attachedfiltersmodel.h"
#include "models/metadatamodel.h"
#include "models/multitrackmodel.h"
#include "models/subtitles.h"
#include "models/subtitlesmodel.h"
#include "qmltypes/qmlfilter.h"
#include "qmltypes/qmlmetadata.h"

#include <QAbstractButton>
#include <QApplication>
#include <QDialog>
#include <QLabel>
#include <QMessageBox>
#include <QDockWidget>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalServer>
#include <QLocalSocket>
#include <QTimer>
#include <QUndoStack>
#include <QDir>
#include <QLockFile>
#include <QSaveFile>
#include <QRegularExpression>
#include <QFutureWatcher>
#include <QPointer>
#include <QStatusBar>
#include <QtConcurrent/QtConcurrentRun>

using namespace BridgeHelpers;

static void retainPreparedProfile(mlt_service service, const std::shared_ptr<Mlt::Profile> &profile,
                                  QSet<mlt_service> &visited)
{
    if (!service || visited.contains(service))
        return;
    visited.insert(service);
    mlt_properties_set_data(mlt_service_properties(service), "_letitedit_prepared_profile",
        new std::shared_ptr<Mlt::Profile>(profile), 0,
        [](void *owner) { delete static_cast<std::shared_ptr<Mlt::Profile> *>(owner); }, nullptr);
    for (int index = 0; index < mlt_service_filter_count(service); ++index)
        retainPreparedProfile(MLT_FILTER_SERVICE(mlt_service_filter(service, index)), profile, visited);
    const auto type = mlt_service_identify(service);
    if (type == mlt_service_playlist_type) {
        const auto playlist = reinterpret_cast<mlt_playlist>(service);
        for (int index = 0; index < mlt_playlist_count(playlist); ++index)
            retainPreparedProfile(MLT_PRODUCER_SERVICE(mlt_playlist_get_clip(playlist, index)), profile, visited);
    } else if (type == mlt_service_multitrack_type) {
        const auto multitrack = reinterpret_cast<mlt_multitrack>(service);
        for (int index = 0; index < mlt_multitrack_count(multitrack); ++index)
            retainPreparedProfile(MLT_PRODUCER_SERVICE(mlt_multitrack_track(multitrack, index)), profile, visited);
    }
    if (type == mlt_service_producer_type || type == mlt_service_chain_type
        || type == mlt_service_playlist_type || type == mlt_service_multitrack_type
        || type == mlt_service_tractor_type)
        retainPreparedProfile(MLT_PRODUCER_SERVICE(mlt_producer_cut_parent(reinterpret_cast<mlt_producer>(service))),
                              profile, visited);
    retainPreparedProfile(mlt_service_producer(service), profile, visited);
}

void ClaudeBridge::prepareTransaction(const QJsonObject &request, QLocalSocket *socket)
{
    QElapsedTimer phase;
    phase.start();
    if (MAIN.isOpening())
        throw BridgeError("a project is still opening; try again in a moment");
    if (!MLT.isMultitrack())
        throw BridgeError("Open a timeline first");
    if (m_preparingTransaction)
        throw BridgeError("Edit conflict: another AI change is being prepared. Read the timeline again.");
    const auto params = request.value("params").toObject();
    const QString expected = revision();
    const QString project = MAIN.fileName();
    LOG_INFO() << "AI change revision ms" << phase.restart();
    const auto profile = std::make_shared<Mlt::Profile>(::mlt_profile_clone(MLT.profile().get_profile()));
    if (params.contains("expected_revision") && params.value("expected_revision").toString() != expected)
        throw BridgeError("Edit conflict: the timeline changed since it was read. Read it again.");
    QMap<QString, QString> afterXml;
    for (const auto &value : params.value("tracks").toArray()) {
        const auto track = value.toObject();
        const QString name = track.value("name").toString();
        afterXml.insert(name, track.value("xml").toString());
    }
    m_preparingTransaction = true;
    LOG_INFO() << "AI change snapshot ms" << phase.elapsed();
    auto *notice = new QLabel(tr("The AI is changing your timeline"), MAIN.statusBar());
    notice->setObjectName(QStringLiteral("aiTimelineChanging"));
    MAIN.statusBar()->addWidget(notice);
    auto *watcher = new QFutureWatcher<std::shared_ptr<PreparedTransaction>>(this);
    const QPointer<QLocalSocket> pending(socket);
    connect(watcher, &QFutureWatcherBase::finished, this, [this, watcher, pending, notice, request, expected, project]() {
        const auto prepared = watcher->result();
        watcher->deleteLater();
        QElapsedTimer stopPhase;
        stopPhase.start();
        std::shared_ptr<RenderHold> hold;
        if (prepared->error.isEmpty() && pending && pending->state() == QLocalSocket::ConnectedState
            && !MAIN.isOpening() && MAIN.fileName() == project)
            hold = std::make_shared<RenderHold>();
        LOG_INFO() << "AI change consumer shutdown ms" << stopPhase.elapsed();
        QTimer::singleShot(16, this, [this, pending, notice, request, expected, project, prepared, hold]() {
            MAIN.statusBar()->removeWidget(notice);
            notice->deleteLater();
            m_preparingTransaction = false;
            if (!pending || pending->state() != QLocalSocket::ConnectedState)
                return;
            QJsonObject response;
            QElapsedTimer phase;
            phase.start();
            if (!prepared->error.isEmpty()) {
                response = {{"id", request.value("id")}, {"ok", false}, {"error", prepared->error}};
            } else if (MAIN.isOpening() || MAIN.fileName() != project || revision() != expected) {
                response = {{"id", request.value("id")}, {"ok", false},
                            {"error", "Edit conflict: the timeline changed while the AI prepared its change. Read it again."}};
            } else {
                LOG_INFO() << "AI change final revision ms" << phase.restart();
                m_preparedTransaction = prepared;
                response = handle(request);
                m_preparedTransaction.reset();
                if (hold)
                    hold->release();
                LOG_INFO() << "AI change commit ms" << phase.elapsed();
                if (response.value("ok").toBool()) {
                    auto *revisionWatcher = new QFutureWatcher<QString>(this);
                    connect(revisionWatcher, &QFutureWatcherBase::finished, this,
                            [revisionWatcher, pending, response]() mutable {
                        const QString committedRevision = revisionWatcher->result();
                        revisionWatcher->deleteLater();
                        if (!pending || pending->state() != QLocalSocket::ConnectedState)
                            return;
                        auto result = response.value("result").toObject();
                        result.insert("revision", committedRevision);
                        response.insert("result", result);
                        pending->write(QJsonDocument(response).toJson(QJsonDocument::Compact) + '\n');
                        pending->flush();
                    });
                    revisionWatcher->setFuture(revisionAsync());
                    LOG_INFO() << "AI change revision snapshot ms" << phase.elapsed();
                    return;
                }
            }
            pending->write(QJsonDocument(response).toJson(QJsonDocument::Compact) + '\n');
            pending->flush();
        });
    });
    watcher->setFuture(QtConcurrent::run([afterXml, profile]() {
        auto prepared = std::make_shared<PreparedTransaction>();
        const auto parse = [&prepared, &profile](const QMap<QString, QString> &xml,
                                      QMap<QString, std::shared_ptr<Mlt::Producer>> &tracks) {
            for (auto entry = xml.cbegin(); entry != xml.cend(); ++entry) {
                auto producer = std::shared_ptr<Mlt::Producer>(
                    new Mlt::Producer(*profile, "xml-string", entry.value().toUtf8().constData()),
                    [](Mlt::Producer *retired) { (void) QtConcurrent::run([retired] { delete retired; }); });
                if (!producer->is_valid() || producer->type() != mlt_service_playlist_type) {
                    prepared->error = "Track " + entry.key() + ": invalid MLT playlist; no changes made";
                    return;
                }
                producer->set("mlt_type", "mlt_producer");
                producer->set("mlt_service", "playlist");
                producer->set("xml", nullptr);
                QSet<mlt_service> visited;
                retainPreparedProfile(producer->get_service(), profile, visited);
                tracks.insert(entry.key(), producer);
            }
        };
        try {
            parse(afterXml, prepared->after);
        } catch (const std::exception &error) {
            prepared->error = QString::fromUtf8(error.what());
        } catch (...) {
            prepared->error = "Could not prepare the timeline change; no changes made";
        }
        return prepared;
    }));
}

QJsonValue ClaudeBridge::synchronizedDelete(const QJsonObject &params)
{
    if(!MLT.isMultitrack())throw BridgeError("Open a timeline first");
    const int a=requireInt(params,"start_frame"),b=requireInt(params,"end_frame");
    auto *t=MAIN.timelineDock();auto *m=t->model();
    if(a<0 || b<=a || !m->tractor() || b>m->tractor()->get_playtime())throw BridgeError("Invalid range; end_frame is exclusive");
    if(params.value("expected_revision").toString()!=revision())throw BridgeError("Edit conflict: refresh live_context and preview again");
    QJsonArray affected;
    for(int tr=0;tr<m->rowCount();++tr){
        if(t->isTrackLocked(tr))throw BridgeError("Unlock all tracks before a synchronized deletion; no changes made");
        const auto parent=m->index(tr,0);
        int count=0;
        for(int i=0;i<m->rowCount(parent);++i){
            auto c=m->index(i,0,parent);int s=c.data(MultitrackModel::StartRole).toInt(),e=s+c.data(MultitrackModel::DurationRole).toInt();
            if(e>a && s<b){
                ++count;
                if(c.data(MultitrackModel::IsTransitionRole).toBool())throw BridgeError("Range overlaps a transition; adjust the range before synchronized deletion");
            }
        }
        affected.append(QJsonObject{{"track",parent.data(MultitrackModel::NameRole).toString()},{"overlappingItems",count}});
    }
    if(params.value("gap_only").toBool()){
        int tr=requireInt(params,"track");
        if(tr<0 || tr>=m->rowCount())throw BridgeError("Invalid gap track");
        auto idx=m->index(t->clipIndexAtPosition(tr,a),0,m->index(tr,0));
        if(!idx.isValid() || !idx.data(MultitrackModel::IsBlankRole).toBool()
           || idx.data(MultitrackModel::StartRole).toInt()!=a
           || idx.data(MultitrackModel::DurationRole).toInt()!=b-a)throw BridgeError("Select one complete gap; no changes made");
    }
    QJsonObject result{{"start_frame",a},{"end_frame",b},{"removed_frames",b-a},{"affected_tracks",affected},
        {"captions","Contained cues removed, crossing cues trimmed, later cues shifted"},{"undo","One native Undo step"}};
    if(params.value("preview").toBool(true)){result["applied"]=false;return result;}
    // Recovery copy without Save As, reopening the project, or resetting the undo stack.
    const QString dir=aiRootPath(QStringLiteral("instances/"))+m_instanceId+"/recovery";QDir().mkpath(dir);
    const QString path=dir+"/before-sync-delete-"+QUuid::createUuid().toString(QUuid::Id128)+".mlt";
    QSaveFile recovery(path);
    if(!recovery.open(QIODevice::WriteOnly))throw BridgeError("Cannot create recovery snapshot; edit not applied");
    recovery.write(projectXml().toString().toUtf8());
    if(!recovery.commit())throw BridgeError("Cannot save recovery snapshot; edit not applied");
    MAIN.undoStack()->push(new AiDeleteSectionCommand(t,a,b,MLT.profile().fps()));
    result["applied"]=true;result["recovery"]=path;result["revision"]=revision();return result;
}

QJsonValue ClaudeBridge::subtitleEdit(const QJsonObject &params)
{
    if(params.value("expected_revision").toString()!=revision())throw BridgeError("Edit conflict: refresh live_context");
    auto *m=MAIN.timelineDock()->subtitlesModel();auto *sel=MAIN.timelineDock()->subtitlesSelectionModel();
    int tr=params.value("track").toInt(sel->selectedTrack());
    if(tr<0 || tr>=m->trackCount())throw BridgeError("Select a subtitle track");
    QJsonArray rows=params.contains("rows")?params.value("rows").toArray():QJsonArray::fromVariantList(sel->selectedItems());
    QList<int> indices;
    for(auto r:rows){int i=r.toInt(-1);if(i<0||i>=m->itemCount(tr))throw BridgeError("Invalid subtitle row");if(!indices.contains(i))indices.append(i);}
    if(indices.isEmpty())throw BridgeError("Select subtitle rows, not text characters");
    std::sort(indices.begin(),indices.end());
    const QString action=params.value("action").toString("remove");
    if(action!="remove" && action!="set_text")throw BridgeError("Supported subtitle actions: remove, set_text");
    if(action=="set_text" && (indices.size()!=1 || !params.contains("text")))throw BridgeError("Select one row and supply text");
    MAIN.undoStack()->beginMacro(action=="remove"?"Remove captions only":"Edit caption wording");
    if(action=="remove")for(int n=indices.size()-1;n>=0;--n)m->removeItems(tr,indices[n],indices[n]);
    else m->setText(tr,indices[0],params.value("text").toString());
    MAIN.undoStack()->endMacro();return QJsonObject{{"changed",indices.size()},{"revision",revision()}};
}

// The timeline's whole marker list as a request gives it ([{text, start, end, color}], frames; color '#rrggbb'),
// checked before anything changes (set_markers, and apply_transaction's markers since T356).
static QList<Markers::Marker> markerListOf(const QJsonArray &array)
{
    QList<Markers::Marker> next;
    for(const auto &value: array){
        const QJsonObject o=value.toObject();
        Markers::Marker m;
        m.text=o.value("text").toString();
        m.start=o.value("start").toInt(-1);
        m.end=o.value("end").toInt(m.start);
        m.color=QColor(o.value("color").toString());
        if(m.start<0 || m.end<m.start)throw BridgeError("A marker needs 0 <= start <= end (frames); no changes made");
        if(!m.color.isValid())m.color=QColor(QStringLiteral("#00ff00"));
        next.append(m);
    }
    return next;
}

// Whether the timeline's markers are already exactly this list.
static bool sameMarkers(const QList<Markers::Marker> &now, const QList<Markers::Marker> &next)
{
    if(now.size()!=next.size())return false;
    for(int i=0;i<now.size();++i)
        if(now[i].text!=next[i].text || now[i].start!=next[i].start || now[i].end!=next[i].end
           || now[i].color.name()!=next[i].color.name())return false;
    return true;
}

// The timeline's markers become `next`, as undo commands pushed into whatever undo step is open.
static void replaceMarkers(MarkersModel *model, const QList<Markers::Marker> &now, const QList<Markers::Marker> &next)
{
    if(!now.isEmpty())model->clear();
    for(const auto &m: next)model->append(m);
}

// AI markers (T298): params {label, markers: [{text, start, end, color}], expected_revision?}. The timeline's whole
// marker list becomes this one (frames; color '#rrggbb'), as one undo step named by label, so a tool's markers land in
// an open window, unsaved changes and all, without saving or reloading it. The same list changes nothing.
QJsonValue ClaudeBridge::setMarkers(const QJsonObject &params)
{
    if(!MLT.isMultitrack())throw BridgeError("Open a timeline first");
    if(params.contains("expected_revision") && params.value("expected_revision").toString()!=revision())
        throw BridgeError("Edit conflict: refresh live_context");
    const QList<Markers::Marker> next=markerListOf(params.value("markers").toArray());
    MarkersModel *model=MAIN.timelineDock()->markersModel();
    const QList<Markers::Marker> now=model->getMarkers();
    if(sameMarkers(now,next))return QJsonObject{{"changed",false},{"markers",next.size()},{"revision",revision()}};
    MAIN.undoStack()->beginMacro(params.value("label").toString(QStringLiteral("AI markers")));
    replaceMarkers(model,now,next);
    MAIN.undoStack()->endMacro();
    return QJsonObject{{"changed",true},{"markers",next.size()},{"revision",revision()}};
}

// AI edit-script apply: params {label, tracks: [{name, xml}], captions?: [{track, cues: [{start_ms, end_ms, text}]}],
// expected_revision?}. Each xml is an MLT document whose root producer is the track's new playlist.
QJsonValue ClaudeBridge::replaceTracks(const QJsonObject &params)
{
    if(!MLT.isMultitrack())throw BridgeError("Open a timeline first");
    if(!m_preparedTransaction && params.contains("expected_revision") && params.value("expected_revision").toString()!=revision())
        throw BridgeError("Edit conflict: the timeline changed since it was read. Read it again.");
    auto *t=MAIN.timelineDock();auto *m=t->model();
    QMap<int,QString> xml;
    for(auto v:params.value("tracks").toArray()){
        const auto o=v.toObject();const QString name=o.value("name").toString();int row=-1;
        for(int r=0;r<m->rowCount();++r)if(m->index(r,0).data(MultitrackModel::NameRole).toString()==name){row=r;break;}
        if(row<0)throw BridgeError("No track named "+name+"; no changes made");
        if(t->isTrackLocked(row))throw BridgeError("Track "+name+" is locked; no changes made");
        const QString doc=o.value("xml").toString();
        if (!m_preparedTransaction) {
            Mlt::Producer test(MLT.profile(),"xml-string",doc.toUtf8().constData());
            if(!test.is_valid())throw BridgeError("Track "+name+": invalid MLT XML; no changes made");
        }
        xml.insert(row,doc);
    }
    QMap<int,QList<Subtitles::SubtitleItem>> caps;
    auto *sub=t->subtitlesModel();
    for(auto v:params.value("captions").toArray()){
        const auto o=v.toObject();int tr=sub->getTrackIndex(o.value("track").toString());
        if(tr<0)throw BridgeError("No caption track named "+o.value("track").toString()+"; no changes made");
        QList<Subtitles::SubtitleItem> items;
        for(auto c:o.value("cues").toArray()){
            const auto q=c.toObject();
            items.append(Subtitles::SubtitleItem{(int64_t)q.value("start_ms").toDouble(),(int64_t)q.value("end_ms").toDouble(),
                                                 q.value("text").toString().toStdString()});
        }
        caps.insert(tr,items);
    }
    if(xml.isEmpty() && caps.isEmpty())throw BridgeError("Nothing to change");
    UndoHelper::PreparedTracks after;
    if (m_preparedTransaction)
        for (auto entry = xml.cbegin(); entry != xml.cend(); ++entry) {
            const QString name = m->index(entry.key(), 0).data(MultitrackModel::NameRole).toString();
            after.insert(entry.key(), m_preparedTransaction->after.value(name));
        }
    MAIN.undoStack()->push(new AiReplaceTracksCommand(t,xml,caps,params.value("label").toString("AI edit"), after));
    return QJsonObject{{"applied",true},{"tracks",xml.size()},{"caption_tracks",caps.size()},{"undo","One native Undo step"},
                       {"revision",m_preparedTransaction ? QString() : revision()}};
}

// One AI edit that may also add or remove tracks, add caption tracks and change track or whole-video effects, on
// the open (possibly unsaved) project, as ONE undo step. Everything is checked before anything changes; a failure
// while applying rolls the whole step back. markers (T356, as set_markers takes them): the timeline's whole marker
// list as the edit leaves it, in the same step, so one Undo puts clips and markers back together; the reply's
// `markers` says the build took them.
namespace {

int transactionTrackRow(MultitrackModel *m, const QString &name)
{
    int found = -1, count = 0;
    for (int r = 0; r < m->rowCount(); ++r)
        if (m->index(r, 0).data(MultitrackModel::NameRole).toString() == name) {
            found = r;
            ++count;
        }
    if (count > 1)
        throw BridgeError("Two tracks are named " + name + "; rename one first; no changes made");
    return found;
}

QList<AiSetFiltersCommand::Props> transactionFilters(const QJsonArray &array, const QString &where)
{
    QList<AiSetFiltersCommand::Props> out;
    for (auto v : array) {
        const auto o = v.toObject();
        const QByteArray svc = o.value("mlt_service").toString().toUtf8();
        Mlt::Filter test(MLT.profile(), svc.constData());
        if (svc.isEmpty() || !test.is_valid())
            throw BridgeError(where + ": unknown effect '" + QString::fromUtf8(svc) + "'; no changes made");
        AiSetFiltersCommand::Props p;
        for (auto it = o.constBegin(); it != o.constEnd(); ++it)
            p.append({it.key().toUtf8(), it.value().isString() ? it.value().toString().toUtf8()
                                                                : QByteArray::number(it.value().toDouble())});
        out.append(p);
    }
    return out;
}

struct Caps { QString track, lang; bool create; QList<Subtitles::SubtitleItem> items; };

struct TransactionPlan
{
    QList<QPair<QString, bool>> adds; // name, video?
    QMap<QString, QString> addAbove;  // a new video track's place: just above this track (default: on top)
    QStringList removes;
    QList<QPair<QString, QString>> contents;
    QList<QPair<QString, QList<AiSetFiltersCommand::Props>>> filterSets; // "" = the whole video
    QList<Caps> captions;
    QList<QPair<QString, QList<AiSetFiltersCommand::Props>>> captionStyles; // a caption track's burn-in filters
    QJsonObject projectProperties;
    bool setMarkers = false;          // markers given (T356): the timeline's whole marker list, in the same step
    QList<Markers::Marker> markers;
};

TransactionPlan validateTransaction(const QJsonObject &params, TimelineDock *t, bool prepared)
{
    auto *m = t->model();
    auto *sub = t->subtitlesModel();
    TransactionPlan plan;
    // check everything first
    QSet<QString> newNames;
    for (auto v : params.value("add_tracks").toArray()) {
        const auto o = v.toObject();
        const QString name = o.value("name").toString(), kind = o.value("kind").toString("video");
        if (name.isEmpty() || (kind != "video" && kind != "audio"))
            throw BridgeError("add_tracks: give each track a name and a kind (video or audio); no changes made");
        if (transactionTrackRow(m, name) >= 0 || newNames.contains(name))
            throw BridgeError("A track named " + name + " already exists; no changes made");
        const QString above = o.value("above").toString();
        if (!above.isEmpty()) {
            if (kind != "video" || transactionTrackRow(m, above) <= 0)
                throw BridgeError("add_tracks: above takes an existing video track below the top one; no changes made");
            plan.addAbove.insert(name, above);
        }
        newNames << name;
        plan.adds.append({name, kind == "video"});
    }
    for (auto v : params.value("remove_tracks").toArray()) {
        const QString name = v.toString();
        const int row = transactionTrackRow(m, name);
        if (row < 0)
            throw BridgeError("No track named " + name + " to remove; no changes made");
        if (t->isTrackLocked(row))
            throw BridgeError("Track " + name + " is locked; no changes made");
        plan.removes << name;
    }
    for (auto v : params.value("tracks").toArray()) {
        const auto o = v.toObject();
        const QString name = o.value("name").toString();
        if (!newNames.contains(name)) {
            const int row = transactionTrackRow(m, name);
            if (row < 0)
                throw BridgeError("No track named " + name + "; no changes made");
            if (t->isTrackLocked(row))
                throw BridgeError("Track " + name + " is locked; no changes made");
        }
        const QString doc = o.value("xml").toString();
        if (!prepared) {
            Mlt::Producer test(MLT.profile(), "xml-string", doc.toUtf8().constData());
            if (!test.is_valid())
                throw BridgeError("Track " + name + ": invalid MLT XML; no changes made");
        }
        plan.contents.append({name, doc});
    }
    if (params.contains("master_filters"))
        plan.filterSets.append({QString(), transactionFilters(params.value("master_filters").toArray(), "master_filters")});
    for (auto v : params.value("track_filters").toArray()) {
        const auto o = v.toObject();
        const QString name = o.value("name").toString();
        if (!newNames.contains(name)) {
            const int row = transactionTrackRow(m, name);
            if (row < 0)
                throw BridgeError("No track named " + name + " for its effects; no changes made");
            // a lock protects everything on the track, its effects and sound settings too
            if (t->isTrackLocked(row))
                throw BridgeError("Track " + name + " is locked, so its effects and sound can't change. Unlock it "
                                  "(the lock on the track's head) or leave it out of this edit; no changes made");
        }
        plan.filterSets.append({name, transactionFilters(o.value("filters").toArray(), "track_filters " + name)});
    }
    QSet<QString> newCaptionTracks;
    for (auto v : params.value("captions").toArray()) {
        const auto o = v.toObject();
        Caps c{o.value("track").toString(), o.value("lang").toString("eng"), false, {}};
        if (sub->getTrackIndex(c.track) < 0) {
            if (!o.value("create").toBool())
                throw BridgeError("No caption track named " + c.track + "; no changes made");
            c.create = true;
            newCaptionTracks << c.track;
        }
        for (auto q : o.value("cues").toArray()) {
            const auto cue = q.toObject();
            c.items.append(Subtitles::SubtitleItem{(int64_t) cue.value("start_ms").toDouble(),
                                                   (int64_t) cue.value("end_ms").toDouble(),
                                                   cue.value("text").toString().toStdString()});
        }
        plan.captions.append(c);
    }
    // how caption tracks are drawn on the video (place, size, outline, colours): each track's burn-in filters
    for (auto v : params.value("caption_styles").toArray()) {
        const auto o = v.toObject();
        const QString track = o.value("track").toString();
        if (track.isEmpty() || (sub->getTrackIndex(track) < 0 && !newCaptionTracks.contains(track)))
            throw BridgeError("caption_styles: no caption track named " + track + "; no changes made");
        auto filters = transactionFilters(o.value("filters").toArray(), "caption_styles " + track);
        for (auto &p : filters) {
            bool isSubtitle = false;
            for (auto it = p.begin(); it != p.end(); ++it) {
                if (it->first == "mlt_service" && it->second == "subtitle")
                    isSubtitle = true;
                if (it->first == "feed")
                    it->second = track.toUtf8();
            }
            if (!isSubtitle)
                throw BridgeError("caption_styles " + track + ": only subtitle burn-in filters can be set; no changes made");
            if (std::none_of(p.cbegin(), p.cend(), [](const auto &kv) { return kv.first == "feed"; }))
                p.append({QByteArray("feed"), track.toUtf8()});
        }
        plan.captionStyles.append({track, filters});
    }
    // properties of the project itself, set on the main tractor in the same step (STYLES.md 5.4): only letitedit's
    // own (letitedit_ai:*), a string or null (removes it)
    plan.projectProperties = params.value("project_properties").toObject();
    for (auto it = plan.projectProperties.begin(); it != plan.projectProperties.end(); ++it) {
        if (!it.key().startsWith(QLatin1String("letitedit_ai:")))
            throw BridgeError("project_properties: only letitedit_ai:* properties can be set (got " + it.key()
                              + "); no changes made");
        if (!it.value().isString() && !it.value().isNull())
            throw BridgeError("project_properties: " + it.key() + " takes a string or null; no changes made");
    }
    // the timeline's markers as the edit leaves them (T356: markers that follow their clips), in the same undo step
    if (params.contains("markers")) {
        plan.setMarkers = true;
        plan.markers = markerListOf(params.value("markers").toArray());
    }
    if (plan.adds.isEmpty() && plan.removes.isEmpty() && plan.contents.isEmpty() && plan.filterSets.isEmpty() && plan.captions.isEmpty()
        && plan.captionStyles.isEmpty() && plan.projectProperties.isEmpty() && !plan.setMarkers)
        throw BridgeError("Nothing to change");
    return plan;
}

} // namespace

QJsonValue ClaudeBridge::applyTransaction(const QJsonObject &params)
{
    if (!MLT.isMultitrack())
        throw BridgeError("Open a timeline first");
    if (!m_preparedTransaction && params.contains("expected_revision") && params.value("expected_revision").toString() != revision())
        throw BridgeError("Edit conflict: the timeline changed since it was read. Read it again.");
    auto *t = MAIN.timelineDock();
    auto *m = t->model();
    auto *sub = t->subtitlesModel();
    const QString label = params.value("label").toString("AI edit");
    const TransactionPlan plan = validateTransaction(params, t, bool(m_preparedTransaction));

    // then apply, as one undo step
    auto *stack = MAIN.undoStack();
    QElapsedTimer commitPhase;
    commitPhase.start();
    RenderHold hold; // tracks come and go in this step too
    bool markersChanged = false;
    LOG_INFO() << "AI transaction stop ms" << commitPhase.restart();
    stack->beginMacro(label);
    try {
        for (const auto &add : plan.adds) {
            QSet<QString> names;
            for (int r = 0; r < m->rowCount(); ++r)
                names << m->index(r, 0).data(MultitrackModel::NameRole).toString();
            int row = -1;
            if (plan.addAbove.contains(add.first)) {
                // the new row takes this track's place in the list: just above it in the stack
                row = transactionTrackRow(m, plan.addAbove.value(add.first));
                stack->push(new Timeline::InsertTrackCommand(*m, row, VideoTrackType));
            } else {
                stack->push(new Timeline::AddTrackCommand(*m, add.second));
                for (int r = 0; r < m->rowCount(); ++r)
                    if (!names.contains(m->index(r, 0).data(MultitrackModel::NameRole).toString()))
                        row = r;
            }
            if (row < 0)
                throw BridgeError("Could not add the track " + add.first);
            stack->push(new Timeline::NameTrackCommand(*m, row, add.first));
        }
        for (const auto &name : plan.removes)
            stack->push(new Timeline::RemoveTrackCommand(*m, transactionTrackRow(m, name)));
        for (const auto &c : plan.captions)
            if (c.create)
                stack->push(new Subtitles::InsertTrackCommand(*sub, SubtitlesModel::SubtitleTrack{c.track, c.lang},
                                                              sub->trackCount()));
        QMap<int, QString> xml;
        for (const auto &c : plan.contents)
            xml.insert(transactionTrackRow(m, c.first), c.second);
        QMap<int, QList<Subtitles::SubtitleItem>> caps;
        for (const auto &c : plan.captions)
            caps.insert(sub->getTrackIndex(c.track), c.items);
        UndoHelper::PreparedTracks after;
        if (m_preparedTransaction)
            for (const auto &content : plan.contents) {
                const int row = transactionTrackRow(m, content.first);
                after.insert(row, m_preparedTransaction->after.value(content.first));
            }
        if (!xml.isEmpty() || !caps.isEmpty())
            stack->push(new AiReplaceTracksCommand(t, xml, caps, label, after));
        for (const auto &set : plan.filterSets)
            stack->push(new AiSetFiltersCommand(t, set.first, set.second, label));
        for (const auto &style : plan.captionStyles)
            stack->push(new AiSetCaptionStyleCommand(t, style.first, style.second, label));
        if (!plan.projectProperties.isEmpty())
            stack->push(MyStyle::projectPropertiesCommand(plan.projectProperties, label));
        if (plan.setMarkers) {
            MarkersModel *markers = t->markersModel();
            const QList<Markers::Marker> now = markers->getMarkers();
            markersChanged = !sameMarkers(now, plan.markers);
            if (markersChanged)
                replaceMarkers(markers, now, plan.markers);
        }
    } catch (...) {
        stack->endMacro();
        stack->undo();
        throw;
    }
    stack->endMacro();
    LOG_INFO() << "AI transaction mutations ms" << commitPhase.restart();
    // a change to effects alone touches no track's contents, so nothing else would say the project has unsaved work
    if (!plan.filterSets.isEmpty() || !plan.captionStyles.isEmpty())
        MAIN.setWindowModified(true);
    hold.release();
    QJsonObject result{{"applied", true}, {"added_tracks", plan.adds.size()}, {"removed_tracks", plan.removes.size()},
                       {"tracks", plan.contents.size()}, {"caption_tracks", plan.captions.size()},
                       {"effect_sets", plan.filterSets.size()}, {"caption_styles", plan.captionStyles.size()}, {"project_properties", plan.projectProperties.size()},
                       {"look", MyStyle::projectStyle(&MAIN)}, {"undo", "One native Undo step"},
                       {"revision", m_preparedTransaction ? QString() : revision()}};
    if (plan.setMarkers) // a build that takes markers says so (an older one ignores them and leaves this out)
        result.insert("markers", QJsonObject{{"count", plan.markers.size()}, {"changed", markersChanged}});
    return result;
}

void ClaudeBridge::installCollaborationUi()
{
    QMenu *menu=nullptr;
    for(auto *action:MAIN.menuBar()->actions())if(action->text()=="AI")menu=action->menu();
    if(!menu)return;
    // How to: where each button is, what it does, how to undo it (command-reference.json, the same text the AI's
    // letitedit_command_help searches). Every word typed must be found; titles first. "Do it" runs the command.
    auto *help=menu->addAction(tr("How to..."));help->setObjectName("aiAssistCommandHelp");
    help->setToolTip(tr("Find how to do something in letitedit: where the button is, what it does, how to undo it"));
    connect(help,&QAction::triggered,this,[this]{
        auto *d=new QDialog(&MAIN);d->setAttribute(Qt::WA_DeleteOnClose);d->setObjectName("howToDialog");
        d->setWindowTitle(tr("How to"));d->resize(760,570);
        auto *layout=new QVBoxLayout(d);auto *search=new QLineEdit(d);search->setObjectName("howToSearch");
        search->setPlaceholderText(tr("What do you want to do? e.g. new video, opening, review, captions, music, undo"));
        search->setClearButtonEnabled(true);
        auto *body=new QTextBrowser(d);body->setObjectName("howToBody");body->setOpenLinks(false);
        layout->addWidget(search);layout->addWidget(body);
        connect(body,&QTextBrowser::anchorClicked,d,[d](const QUrl &url){
            if(url.scheme()!=QLatin1String("action"))return;
            if(auto *a=findAction(url.path())){ if(a->isEnabled()){d->close();a->trigger();} }
        });
        auto render=[this,body](const QString &q){
            static const QList<QPair<QString,QString>> fields{{"selection",tr("Where")},{"behavior",tr("What it does")},
                {"shortcut",tr("Shortcut")},{"example",tr("Try saying")},{"limits",tr("Limits")}};
            QString html;
            try{
                const QStringList words=q.simplified().toLower().split(QLatin1Char(' '),Qt::SkipEmptyParts);
                QList<QPair<int,QJsonObject>> hits;
                for(auto v:commandHelp({}).toArray()){
                    const auto o=v.toObject();
                    const QString title=o.value("title").toString().toLower();
                    const QString all=QString::fromUtf8(QJsonDocument(o).toJson()).toLower();
                    int score=0; bool every=true;
                    for(const auto &w:words){ if(title.contains(w))score+=3; else if(all.contains(w))score+=1; else every=false; }
                    if(every)hits.append({score,o});
                }
                std::stable_sort(hits.begin(),hits.end(),[](const auto &a,const auto &b){return a.first>b.first;});
                for(const auto &hit:hits){
                    const auto &o=hit.second;
                    html+="<h3>"+o["title"].toString().toHtmlEscaped()+"</h3>";
                    for(const auto &f:fields){
                        const QString text=o.value(f.first).toString();
                        if(!text.isEmpty())html+="<p><b>"+f.second.toHtmlEscaped()+":</b> "+text.toHtmlEscaped()+"</p>";
                    }
                    if(o.value("enabled_now").toBool() && !o.value("action").toString().isEmpty())
                        html+=QStringLiteral("<p><a href=\"action:%1\">%2</a></p>").arg(o.value("action").toString(),tr("Do it now"));
                }
            }catch(const BridgeError &e){html=e.message.toHtmlEscaped();}
            body->setHtml(html.isEmpty()?tr("Nothing found for that. Try fewer or other words, or ask your AI."):html);
        };connect(search,&QLineEdit::textChanged,d,render);render("");d->show();
    });
    auto add=[this,menu](const QString &label,bool gap){
        auto *action=menu->addAction(label);action->setObjectName(gap?"aiAssistCloseGapSync":"aiAssistDeleteSectionSync");
        connect(action,&QAction::triggered,this,[this,gap]{
            auto *t=MAIN.timelineDock();int a=-1,b=-1; if(!t->selection().isEmpty())t->getSelectionRange(&a,&b);
            if(a<0){MAIN.showStatusMessage(tr("Select a clip or gap first, or ask your AI to delete an exact range."));return;}
            auto *d=new QDialog(&MAIN);d->setAttribute(Qt::WA_DeleteOnClose);d->setWindowTitle(gap?"Close gap in sync":"Delete section in sync");
            auto *l=new QFormLayout(d);auto *start=new QSpinBox(d);auto *end=new QSpinBox(d);
            const int length=MLT.producer()->get_length();start->setRange(0,length);end->setRange(1,length);start->setValue(a);end->setValue(b); // getSelectionRange gives an exclusive end
            l->addRow("First frame:",start);l->addRow("End frame (exclusive):",end);
            auto *info=new QLabel("Closes this time range across all tracks, captions and markers.\nCrossing cues are trimmed. One Undo restores everything.",d);l->addRow(info);
            auto rev=revision();int tr=t->currentTrack();
            auto *buttons=new QDialogButtonBox(QDialogButtonBox::Ok|QDialogButtonBox::Cancel,d);l->addRow(buttons);
            connect(buttons,&QDialogButtonBox::rejected,d,&QDialog::reject);
            connect(buttons,&QDialogButtonBox::accepted,d,[this,d,start,end,rev,gap,tr,info]{
                try{synchronizedDelete({{"start_frame",start->value()},{"end_frame",end->value()},{"expected_revision",rev},{"preview",false},{"gap_only",gap},{"track",tr}});d->accept();}
                catch(const BridgeError &e){info->setText(e.message);}
            });d->show();
        });
    };
    add("Delete section and close gap (in sync)…",false);add("Close selected gap (in sync)…",true);
    if(auto *remove=findAction("subtitleRemoveItemAction"))menu->addAction(remove);
}
