/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Two folder-backed audio libraries shared with the local MCP server.
 */
#ifndef AIAUDIOLIBRARY_H
#define AIAUDIOLIBRARY_H
#include "letitedit/panels/musicpicker.h"
#include "letitedit/airoot.h"
#include "mainwindow.h"
#include "docks/timelinedock.h"
#include "mltcontroller.h"
#include <QApplication>
#include <QDirIterator>
#include <QDockWidget>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QJsonArray>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QPushButton>
#include <QSaveFile>
#include <QTabWidget>
#include "letitedit/dialogs/lefeatures.h"
#include <QVBoxLayout>
#include <QScrollArea>

inline QString aiAudioConfigPath() { return aiRootPath(QStringLiteral("appdata/ai-audio-libraries.json")); }
inline QJsonObject aiAudioConfig()
{
    QFile file(aiAudioConfigPath());
    return file.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(file.readAll()).object() : QJsonObject();
}

inline void installAiAudioLibrary(MainWindow *window, QMenu *menu)
{
    auto dock = new QDockWidget(QStringLiteral("Music & sound"), window);
    dock->setObjectName(QStringLiteral("aiAudioLibraryDock"));
    dock->toggleViewAction()->setObjectName(QStringLiteral("aiAudioLibraryAction"));
    menu->addAction(dock->toggleViewAction());
    auto body = new QWidget(dock);
    auto layout = new QVBoxLayout(body);
    auto tabs = new QTabWidget(body); tabs->setObjectName(QStringLiteral("aiAudioTabs"));
    layout->addWidget(tabs);
    // Music: the same list and fitting as the timeline's Add music (best fit first, ducked under talking)
    auto musicScroll = new QScrollArea(tabs);
    musicScroll->setObjectName(QStringLiteral("musicScroll"));
    musicScroll->setWidgetResizable(true);
    musicScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    musicScroll->setMinimumSize(0, 0);
    musicScroll->setWidget(MusicPicker::createMusicPanel(window, musicScroll));
    tabs->addTab(musicScroll, QStringLiteral("Music"));
    for (const auto &kind : {QStringLiteral("sfx")}) {
        auto page = new QWidget(tabs);
        auto column = new QVBoxLayout(page);
        auto folderRow = new QHBoxLayout();
        auto folder = new QLineEdit(page); folder->setObjectName("aiAudioFolder_" + kind);
        folder->setPlaceholderText(QStringLiteral("Choose or paste a library folder"));
        folder->setText(aiAudioConfig().value(kind + "_folder").toString());
        auto browse = new QPushButton(QStringLiteral("Choose folder…"), page);
        folderRow->addWidget(folder,1); folderRow->addWidget(browse); column->addLayout(folderRow);
        auto search = new QLineEdit(page); search->setObjectName("aiAudioSearch_" + kind);
        search->setPlaceholderText(QStringLiteral("Search filenames and subfolders…"));column->addWidget(search);
        auto list = new QListWidget(page);list->setObjectName("aiAudioList_"+kind);
        list->setSelectionMode(QAbstractItemView::SingleSelection);column->addWidget(list,1);
        auto status = new QLabel(page);status->setObjectName("aiAudioStatus_"+kind);status->setWordWrap(true);column->addWidget(status);
        auto buttons = new QHBoxLayout();
        auto refresh = new QPushButton(QStringLiteral("Refresh"),page);refresh->setObjectName("aiAudioRefresh_"+kind);
        auto preview = new QPushButton(QStringLiteral("Preview"),page);preview->setObjectName("aiAudioPreview_"+kind);
        auto add = new QPushButton(QStringLiteral("Add at playhead"),page);add->setObjectName("aiAudioAdd_"+kind);
        add->setToolTip(QStringLiteral("Adds a new audio track at the timeline playhead, leaving existing clips in place. Undo reverses it."));
        buttons->addWidget(refresh);buttons->addWidget(preview);buttons->addWidget(add);column->addLayout(buttons);
        const auto filter = [list,search]() {
            for(int i=0;i<list->count();++i)list->item(i)->setHidden(!list->item(i)->text().contains(search->text(),Qt::CaseInsensitive));
        };
        const auto reload = [folder,list,status,kind,filter]() {
            folder->setText(aiAudioConfig().value(kind+"_folder").toString());list->clear();
            const QFileInfo rootInfo(folder->text());
            if(folder->text().isEmpty() || !rootInfo.isDir()) {status->setText(QStringLiteral("Choose an available library folder."));return;}
            const QString root = rootInfo.canonicalFilePath();
            const QStringList extensions={"wav","mp3","flac","m4a","aac","ogg","opus","aiff","aif","wma"};
            QDirIterator it(root,QDir::Files,QDirIterator::Subdirectories);
            while(it.hasNext()) {
                QFileInfo file(it.next()); const auto canonical=file.canonicalFilePath();
                if(!extensions.contains(file.suffix().toLower()) || !canonical.startsWith(root+"/",Qt::CaseInsensitive))continue;
                auto item=new QListWidgetItem(QDir(root).relativeFilePath(file.absoluteFilePath()),list);
                item->setData(Qt::UserRole,file.absoluteFilePath());item->setToolTip(file.absoluteFilePath());
            }
            list->sortItems();filter();status->setText(QStringLiteral("%1 audio files · Preview opens the Source player").arg(list->count()));
        };
        const auto saveFolder = [folder,status,kind,reload]() {
            const QFileInfo info(folder->text());
            if(!info.isDir()) {status->setText(QStringLiteral("That folder is unavailable. Previous setting kept."));return;}
            auto config=aiAudioConfig();config.insert(kind+"_folder",info.absoluteFilePath());
            QSaveFile file(aiAudioConfigPath());
            if(!file.open(QIODevice::WriteOnly)) {status->setText(QStringLiteral("Could not save library settings."));return;}
            file.write(QJsonDocument(config).toJson());
            if(!file.commit()) {status->setText(QStringLiteral("Could not save library settings."));return;}
            reload();
        };
        QObject::connect(folder,&QLineEdit::editingFinished,page,saveFolder);
        QObject::connect(browse,&QPushButton::clicked,page,[folder,page,saveFolder]() {
            auto path=QFileDialog::getExistingDirectory(page,QStringLiteral("Audio library folder"),folder->text());
            if(!path.isEmpty()) {folder->setText(path);saveFolder();}
        });
        QObject::connect(refresh,&QPushButton::clicked,page,reload);
        QObject::connect(search,&QLineEdit::textChanged,page,filter);
        const auto play = [window,list,status]() {
            if(!list->currentItem()) {status->setText(QStringLiteral("Select a sound first."));return;}
            if(!window->open(list->currentItem()->data(Qt::UserRole).toString(),nullptr,true))status->setText(QStringLiteral("Could not open audio."));
        };
        QObject::connect(preview,&QPushButton::clicked,page,play);
        QObject::connect(list,&QListWidget::itemDoubleClicked,page,[play](QListWidgetItem *){play();});
        QObject::connect(add,&QPushButton::clicked,page,[window,list,status,kind]() {
            if(!list->currentItem()) {status->setText(QStringLiteral("Select a sound first."));return;}
            if(!window->isMultitrackValid()) {status->setText(QStringLiteral("Open a timeline project first."));return;}
            const auto path=list->currentItem()->data(Qt::UserRole).toString();
            if(!QFileInfo::exists(path)) {status->setText(QStringLiteral("File moved or unavailable. Refresh the library."));return;}
            Mlt::Producer producer(MLT.profile(),path.toUtf8().constData());
            if(!producer.is_valid()) {status->setText(QStringLiteral("Could not read selected audio."));return;}
            producer.set("shotcut:caption",QFileInfo(path).fileName().toUtf8().constData());
            const QString xml=MLT.XML(&producer);
            auto timeline=window->timelineDock();const int position=qMax(0,timeline->position());
            const int track=timeline->addAudioTrack();
            timeline->setTrackName(track,kind=="sfx"?QStringLiteral("Library SFX"):QStringLiteral("Library Music"));
            timeline->overwrite(track,position,xml,false);
            status->setText(QStringLiteral("Added on a separate audio track at the playhead. Trim and mix to taste."));
        });
        auto intro = new QLabel(QStringLiteral("Your own sound effects folder, below. Added sounds go on their own track at the playhead."), page);
        intro->setWordWrap(true); intro->setProperty("studioMuted", true); column->insertWidget(0, intro);
        // letitedit's free sound effects (the asset library) first: a beginner has no folder of their own yet
        auto library = new QPushButton(QObject::tr("Free sound effects: whooshes, pops, dings..."), page);
        library->setObjectName(QStringLiteral("musicSoundEffects"));
        library->setProperty("studioPrimary", true);
        library->setToolTip(QObject::tr("letitedit's free sound effects (CC0): search, hear and add at the playhead"));
        QObject::connect(library, &QPushButton::clicked, page, [window]() { LeFeatures::showStickers(window, QStringLiteral("sfx")); });
        column->insertWidget(0, library);
        tabs->addTab(page,QStringLiteral("Sound effects"));reload();
    }
    dock->setWidget(body);window->addDockWidget(Qt::RightDockWidgetArea,dock);dock->hide();
}

// Local bridge inspection/testing uses the exact same controls as a person.
inline QJsonObject aiAudioLibraryCommand(MainWindow *window,const QJsonObject &params)
{
    auto dock=window->findChild<QDockWidget *>("aiAudioLibraryDock");
    if(!dock)return {{"error","Audio library panel unavailable"}};
    const QString kind=params.value("kind").toString("sfx");
    if(kind!="sfx"&&kind!="music")return {{"error","Choose sfx or music"}};
    auto tabs=dock->findChild<QTabWidget *>("aiAudioTabs");tabs->setCurrentIndex(kind=="music"?0:1);
    if(kind=="music") {
        // the music panel: the same list as Add music
        if(params.value("show").toBool())MusicPicker::showMusicPanel(window);
        auto list=dock->findChild<QListWidget *>("addMusicList");
        if(params.contains("search"))dock->findChild<QLineEdit *>("addMusicSearch")->setText(params.value("search").toString());
        if(params.contains("select"))for(int i=0;i<list->count();++i)if(list->item(i)->text().contains(params.value("select").toString()))list->setCurrentRow(i);
        if(params.value("add").toBool())dock->findChild<QPushButton *>("addMusicGo")->click();
        bool saved=false;
        if(params.contains("snapshot"))saved=dock->grab().save(params.value("snapshot").toString());
        QJsonArray visible;
        for(int i=0;i<list->count() && visible.size()<100;++i)if(!list->item(i)->isHidden())visible.append(list->item(i)->text());
        return {{"kind",kind},{"total",list->count()},{"visible",visible},{"snapshot_saved",saved},
            {"selected",list->currentItem()?list->currentItem()->text():QString()},
            {"now",dock->findChild<QLabel *>("addMusicNow")->text()},
            {"state",dock->findChild<QWidget *>("musicPanel")->property("musicState").toString()},
            {"use_enabled",dock->findChild<QPushButton *>("addMusicGo")->isEnabled()},
            {"play_enabled",dock->findChild<QPushButton *>("addMusicPlay")->isEnabled()},
            {"dock_visible",dock->isVisible()},
            {"status",dock->findChild<QLabel *>("aiAudioStatus_music")->text()}};
    }
    if(params.value("show").toBool()){dock->show();dock->raise();}
    auto list=dock->findChild<QListWidget *>("aiAudioList_"+kind);
    if(params.value("refresh").toBool())dock->findChild<QPushButton *>("aiAudioRefresh_"+kind)->click();
    if(params.contains("search"))dock->findChild<QLineEdit *>("aiAudioSearch_"+kind)->setText(params.value("search").toString());
    if(params.contains("select")) {
        for(int i=0;i<list->count();++i)if(list->item(i)->text()==params.value("select").toString())list->setCurrentRow(i);
    }
    if(params.value("preview").toBool())dock->findChild<QPushButton *>("aiAudioPreview_"+kind)->click();
    if(params.value("add").toBool())dock->findChild<QPushButton *>("aiAudioAdd_"+kind)->click();
    bool saved=false;
    if(params.contains("snapshot"))saved=dock->grab().save(params.value("snapshot").toString());
    QJsonArray visible;
    for(int i=0;i<list->count() && visible.size()<100;++i)if(!list->item(i)->isHidden())visible.append(list->item(i)->text());
    return {{"kind",kind},{"total",list->count()},{"visible",visible},{"snapshot_saved",saved},
        {"selected",list->currentItem()?list->currentItem()->text():QString()},
        {"status",dock->findChild<QLabel *>("aiAudioStatus_"+kind)->text()}};
}
#endif
