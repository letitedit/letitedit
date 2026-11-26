// Shared native commands: the UI and MCP both call these same operations.
#pragma once
#include "commands/undohelper.h"
#include "dialogs/longuitask.h"
#include "docks/timelinedock.h"
#include "models/subtitlesmodel.h"
#include "models/markersmodel.h"
#include "mltcontroller.h"
#include <QSet>
#include <QElapsedTimer>
#include <QDebug>
#include <QUndoCommand>
#include <QtMath>
#include <algorithm>
#include <memory>

class AiDeleteSectionCommand : public QUndoCommand {
    TimelineDock *t;
    UndoHelper restore;
    int start, end;
    QList<QList<Subtitles::SubtitleItem>> before, after;
    QList<Markers::Marker> markersBefore, markersAfter;
public:
    AiDeleteSectionCommand(TimelineDock *timeline, int a, int b, double fps)
      : t(timeline), restore(*t->model()), start(a), end(b) {
        setText(QStringLiteral("Delete section in sync (%1–%2)").arg(a).arg(b));
        restore.setHints(UndoHelper::RestoreTracks);
        const int64_t am=qRound64(a*1000.0/fps), bm=qRound64(b*1000.0/fps);
        auto mapTime=[am,bm](int64_t x){return x<=am?x:x>=bm?x-(bm-am):am;};
        auto *sub=t->subtitlesModel();
        for(int tr=0;tr<sub->trackCount();++tr){
            QList<Subtitles::SubtitleItem> oldItems,newItems;
            for(int i=0;i<sub->itemCount(tr);++i){
                auto item=sub->getItem(tr,i); oldItems.append(item);
                item.start=mapTime(item.start); item.end=mapTime(item.end);
                if(item.end>item.start)newItems.append(item);
            }
            before.append(oldItems);after.append(newItems);
        }
        markersBefore=t->markersModel()->getMarkers();
        auto mapFrame=[a,b](int x){return x<=a?x:x>=b?x-(b-a):a;};
        for(auto m:markersBefore){
            if(m.start>=a && m.end<b)continue;
            m.start=mapFrame(m.start);m.end=mapFrame(m.end+1)-1;
            if(m.end<m.start)m.end=m.start;
            markersAfter.append(m);
        }
    }
    void redo() override {
        restore.recordBeforeState();
        t->model()->removeTimelineRegion(start,end-start);
        restore.recordAfterState();
        for(int i=0;i<after.size();++i)t->subtitlesModel()->doReplaceItems(i,after[i]);
        t->markersModel()->doReplace(markersAfter);
        t->setSelection(); t->setPosition(start);
    }
    void undo() override {
        restore.undoChanges();
        for(int i=0;i<before.size();++i)t->subtitlesModel()->doReplaceItems(i,before[i]);
        t->markersModel()->doReplace(markersBefore);
    }
};

// Many sections deleted in sync as one undoable step (Remove pauses). Undo rebuilds each track once from
// the state before; a step per section rebuilt every track once per section, which took long and crashed
// the video decoder after a hundred cuts. Tracks in "uncut" (music) are not cut, only shortened to where
// the others now end, so a song plays on instead of jumping at every cut.
class AiDeleteSectionsCommand : public QUndoCommand {
    TimelineDock *t;
    UndoHelper restore;
    QList<QPair<int,int>> sections; // timeline frames, end exclusive, last to first
    QSet<int> uncut, shortened;
    QList<QList<Subtitles::SubtitleItem>> before, after;
    QList<Markers::Marker> markersBefore, markersAfter;
public:
    AiDeleteSectionsCommand(TimelineDock *timeline, QList<QPair<int,int>> cuts, double fps,
                            const QSet<int> &keepWhole, const QString &label)
      : t(timeline), restore(*t->model()), uncut(keepWhole) {
        setText(label);
        restore.setHints(UndoHelper::RestoreTracks);
        std::sort(cuts.begin(),cuts.end(),[](auto x,auto y){return x.first>y.first;});
        sections=cuts;
        auto *sub=t->subtitlesModel();
        for(int tr=0;tr<sub->trackCount();++tr){
            QList<Subtitles::SubtitleItem> items;
            for(int i=0;i<sub->itemCount(tr);++i)items.append(sub->getItem(tr,i));
            before.append(items);
            for(const auto &cut:sections){
                const int64_t am=qRound64(cut.first*1000.0/fps), bm=qRound64(cut.second*1000.0/fps);
                auto mapTime=[am,bm](int64_t x){return x<=am?x:x>=bm?x-(bm-am):am;};
                QList<Subtitles::SubtitleItem> moved;
                for(auto item:items){
                    item.start=mapTime(item.start); item.end=mapTime(item.end);
                    if(item.end>item.start)moved.append(item);
                }
                items=moved;
            }
            after.append(items);
        }
        markersBefore=t->markersModel()->getMarkers();
        markersAfter=markersBefore;
        for(const auto &cut:sections){
            const int a=cut.first,b=cut.second;
            auto mapFrame=[a,b](int x){return x<=a?x:x>=b?x-(b-a):a;};
            QList<Markers::Marker> moved;
            for(auto m:markersAfter){
                if(m.start>=a && m.end<b)continue;
                m.start=mapFrame(m.start);m.end=mapFrame(m.end+1)-1;
                if(m.end<m.start)m.end=m.start;
                moved.append(m);
            }
            markersAfter=moved;
        }
    }
    // Whether an uncut track had to be shortened (it lost its fade-out then).
    bool wasShortened(int track) const { return shortened.contains(track); }
    void redo() override {
        // A hundred cuts in a long video take several seconds: say so instead of looking frozen.
        LongUiTask longTask(text());
        restore.recordBeforeState();
        auto *m=t->model();
        const int tracks=m->trackList().size();
        for(int c=0;c<sections.size();++c){
            if(sections.size()>20 && c%5==0)longTask.reportProgress(QObject::tr("Cutting"),c,sections.size());
            for(int i=0;i<tracks;++i)
                if(!uncut.contains(i))m->removeRegion(i,sections[c].first,sections[c].second-sections[c].first);
        }
        int end=0;
        for(int i=0;i<tracks;++i){
            if(uncut.contains(i))continue;
            QScopedPointer<Mlt::Producer> track(m->tractor()->track(m->trackList().at(i).mlt_index));
            if(track && track->is_valid())end=qMax(end,Mlt::Playlist(*track).get_playtime());
        }
        shortened.clear();
        for(int i:std::as_const(uncut)){
            if(i<0 || i>=tracks)continue;
            QScopedPointer<Mlt::Producer> track(m->tractor()->track(m->trackList().at(i).mlt_index));
            if(!track || !track->is_valid())continue;
            const int playtime=Mlt::Playlist(*track).get_playtime();
            if(end>0 && playtime>end){m->removeRegion(i,end,playtime-end);shortened<<i;}
        }
        emit m->modified();
        restore.recordAfterState();
        for(int i=0;i<after.size();++i)t->subtitlesModel()->doReplaceItems(i,after[i]);
        t->markersModel()->doReplace(markersAfter);
        t->setSelection();
        if(!sections.isEmpty())t->setPosition(sections.last().first);
    }
    void undo() override {
        restore.undoChanges();
        for(int i=0;i<before.size();++i)t->subtitlesModel()->doReplaceItems(i,before[i]);
        t->markersModel()->doReplace(markersBefore);
    }
};

// Replaces the effects of the whole video (track empty) or of one track (by name) with a new list, as one undo
// step. Captions (subtitle_feed, subtitle) and the engine's own loader filters are never touched.
class AiSetFiltersCommand : public QUndoCommand {
public:
    typedef QList<QPair<QByteArray, QByteArray>> Props;
private:
    TimelineDock *t;
    QString trackName;
    QList<Props> before, after;
    std::unique_ptr<Mlt::Service> service() const {
        auto *m = t->model();
        if (!m->tractor())
            return nullptr;
        if (trackName.isEmpty())
            return std::make_unique<Mlt::Service>(m->tractor()->get_service());
        for (int r = 0; r < m->rowCount(); ++r) {
            if (m->index(r, 0).data(MultitrackModel::NameRole).toString() == trackName) {
                std::unique_ptr<Mlt::Producer> track(m->tractor()->track(m->trackList().at(r).mlt_index));
                return track && track->is_valid() ? std::make_unique<Mlt::Service>(track->get_service()) : nullptr;
            }
        }
        return nullptr;
    }
    bool managed(Mlt::Filter &f) const {
        const QString svc = QString::fromUtf8(f.get("mlt_service"));
        if (trackName.isEmpty() && (svc == "subtitle_feed" || svc == "subtitle"))
            return false;
        return !f.get_int("_loader");
    }
    QList<Props> capture() const {
        QList<Props> out;
        auto s = service();
        if (!s)
            return out;
        for (int i = 0; i < s->filter_count(); ++i) {
            std::unique_ptr<Mlt::Filter> f(s->filter(i));
            if (!f || !f->is_valid() || !managed(*f))
                continue;
            Props p;
            for (int k = 0; k < f->count(); ++k) {
                const char *name = f->get_name(k);
                if (name && name[0] != '_' && qstrcmp(name, "mlt_type") != 0)
                    p.append({QByteArray(name), QByteArray(f->get(k) ? f->get(k) : "")});
            }
            out.append(p);
        }
        return out;
    }
    void apply(const QList<Props> &set) {
        auto s = service();
        if (!s)
            return;
        for (int i = s->filter_count() - 1; i >= 0; --i) {
            std::unique_ptr<Mlt::Filter> f(s->filter(i));
            if (f && f->is_valid() && managed(*f))
                s->detach(*f);
        }
        for (const auto &p : set) {
            QByteArray svc;
            for (const auto &kv : p)
                if (kv.first == "mlt_service")
                    svc = kv.second;
            Mlt::Filter f(MLT.profile(), svc.constData());
            if (!f.is_valid())
                continue;
            for (const auto &kv : p)
                if (kv.first != "mlt_service")
                    f.set(kv.first.constData(), kv.second.constData());
            s->attach(f);
        }
        MLT.refreshConsumer();
    }
public:
    AiSetFiltersCommand(TimelineDock *timeline, const QString &track, const QList<Props> &filters,
                        const QString &label)
      : t(timeline), trackName(track), after(filters) {
        setText(label);
        before = capture();
    }
    void redo() override { apply(after); }
    void undo() override { apply(before); }
};

// Sets how one caption track is drawn on the video (its burn-in filters on the whole video: the text and, when there is
// one, its shadow copy: place, size, outline, colours), as one undo step. The same count of filters is set in place, so
// they keep their place among the video's other effects; another count replaces them. Undo puts the old ones back.
class AiSetCaptionStyleCommand : public QUndoCommand {
public:
    typedef AiSetFiltersCommand::Props Props;
private:
    TimelineDock *timeline;
    QString feed;
    QList<Props> before, after;
    std::unique_ptr<Mlt::Service> video() const {
        auto *m = timeline->model();
        return m->tractor() ? std::make_unique<Mlt::Service>(m->tractor()->get_service()) : nullptr;
    }
    static bool isFeed(Mlt::Filter &f, const QString &name) {
        return QString::fromUtf8(f.get("mlt_service")) == QLatin1String("subtitle")
               && QString::fromUtf8(f.get("feed")) == name;
    }
    QList<Props> capture() const {
        QList<Props> out;
        auto tractor = video();
        for (int i = 0; tractor && i < tractor->filter_count(); ++i) {
            std::unique_ptr<Mlt::Filter> f(tractor->filter(i));
            if (!f || !f->is_valid() || !isFeed(*f, feed))
                continue;
            Props p;
            for (int k = 0; k < f->count(); ++k) {
                const char *name = f->get_name(k);
                if (name && name[0] != '_' && qstrcmp(name, "mlt_type") != 0)
                    p.append({QByteArray(name), QByteArray(f->get(k) ? f->get(k) : "")});
            }
            out.append(p);
        }
        return out;
    }
    void apply(const QList<Props> &set) {
        auto tractor = video();
        if (!tractor)
            return;
        QList<int> mine; // the video's filter indexes that draw this track
        for (int i = 0; i < tractor->filter_count(); ++i) {
            std::unique_ptr<Mlt::Filter> f(tractor->filter(i));
            if (f && f->is_valid() && isFeed(*f, feed))
                mine.append(i);
        }
        if (mine.size() == set.size()) {
            for (int n = 0; n < mine.size(); ++n) {
                std::unique_ptr<Mlt::Filter> f(tractor->filter(mine.at(n)));
                for (const auto &kv : set.at(n))
                    if (kv.first != "mlt_service")
                        f->set(kv.first.constData(), kv.second.constData());
            }
        } else {
            for (int n = mine.size() - 1; n >= 0; --n) {
                std::unique_ptr<Mlt::Filter> f(tractor->filter(mine.at(n)));
                tractor->detach(*f);
            }
            for (const auto &p : set) {
                Mlt::Filter f(MLT.profile(), "subtitle");
                if (!f.is_valid())
                    continue;
                for (const auto &kv : p)
                    if (kv.first != "mlt_service")
                        f.set(kv.first.constData(), kv.second.constData());
                tractor->attach(f);
            }
        }
        MLT.refreshConsumer();
        emit timeline->model()->modified();
    }
public:
    AiSetCaptionStyleCommand(TimelineDock *dock, const QString &track, const QList<Props> &filters,
                             const QString &label)
      : timeline(dock), feed(track), after(filters) {
        setText(label);
        before = capture();
    }
    void redo() override { apply(after); }
    void undo() override { apply(before); }
};

// One undoable step for an AI edit made through an edit script: whole tracks are replaced with new
// playlists (rendered from the script) and caption tracks with new cues. Undo restores both exactly.
// The render thread mustn't be inside a track while its contents are replaced: MLT frees what that thread is reading (T96: dumps in
// mlt_service_apply_filters, producer_get_image and consumer_read_ahead_thread, during New hook swaps with the video playing). Stops it
// for the swap and starts it again where it was, playing or paused. Nested holds do nothing more.
class RenderHold {
    bool m_held = false;
    std::unique_ptr<Mlt::Consumer> m_consumer;
public:
    RenderHold() {
        if (MLT.consumer() && MLT.consumer()->is_valid() && !MLT.consumer()->is_stopped()) {
            m_consumer = std::make_unique<Mlt::Consumer>(*MLT.consumer());
            m_consumer->stop();
            m_held = true;
        }
    }
    ~RenderHold() { release(); }
    void release() {
        if (!m_held)
            return;
        m_held = false;
        if (!MLT.consumer() || !MLT.consumer()->is_valid()
            || MLT.consumer()->get_consumer() != m_consumer->get_consumer() || !m_consumer->is_stopped())
            return;
        m_consumer->purge();
        m_consumer->start();
        MLT.refreshConsumer();
    }
    RenderHold(const RenderHold &) = delete;
    RenderHold &operator=(const RenderHold &) = delete;
};

class AiReplaceTracksCommand : public QUndoCommand {
    TimelineDock *t;
    UndoHelper restore;
    QMap<int, QString> tracksXml;
    QMap<int, QList<Subtitles::SubtitleItem>> capsAfter, capsBefore;
    UndoHelper::PreparedTracks preparedTracks;
public:
    AiReplaceTracksCommand(TimelineDock *timeline, const QMap<int, QString> &xml,
                           const QMap<int, QList<Subtitles::SubtitleItem>> &captions, const QString &label,
                           const UndoHelper::PreparedTracks &after = {})
      : t(timeline), restore(*t->model()), tracksXml(xml), capsAfter(captions),
        preparedTracks(after) {
        setText(label);
        restore.setHints(UndoHelper::RestoreTracks);
        auto *sub=t->subtitlesModel();
        for(auto it=capsAfter.constBegin();it!=capsAfter.constEnd();++it){
            QList<Subtitles::SubtitleItem> items;
            for(int i=0;i<sub->itemCount(it.key());++i)items.append(sub->getItem(it.key(),i));
            capsBefore.insert(it.key(),items);
        }
    }
    void redo() override {
        QElapsedTimer phase;
        phase.start();
        RenderHold hold;
        qInfo() << "AI prepared stop ms" << phase.restart();
        if (!preparedTracks.isEmpty()) {
            restore.swapPreparedTracks(preparedTracks);
            qInfo() << "AI prepared swap ms" << phase.restart();
            emit t->model()->modified();
            qInfo() << "AI prepared modified ms" << phase.restart();
            for(auto it=capsAfter.constBegin();it!=capsAfter.constEnd();++it)t->subtitlesModel()->doReplaceItems(it.key(),it.value());
            t->setSelection();
            return;
        }
        QSet<int> scope;
        for(auto it=tracksXml.constBegin();it!=tracksXml.constEnd();++it)scope<<it.key();
        restore.recordBeforeState(scope);
        UndoHelper applier(*t->model());
        applier.setHints(UndoHelper::RestoreTracks);
        applier.restoreTracksFromXml(tracksXml);
        restore.recordAfterState();
        for(auto it=capsAfter.constBegin();it!=capsAfter.constEnd();++it)t->subtitlesModel()->doReplaceItems(it.key(),it.value());
        t->setSelection();
    }
    void undo() override {
        RenderHold hold;
        if (!preparedTracks.isEmpty()) {
            restore.swapPreparedTracks(preparedTracks);
            emit t->model()->modified();
        } else
            restore.undoChanges();
        for(auto it=capsBefore.constBegin();it!=capsBefore.constEnd();++it)t->subtitlesModel()->doReplaceItems(it.key(),it.value());
    }
};
