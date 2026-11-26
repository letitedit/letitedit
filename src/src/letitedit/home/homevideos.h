#ifndef HOMEVIDEOS_H
#define HOMEVIDEOS_H

#include "letitedit/airoot.h"
#include "letitedit/newvideo/learnlooks.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "settings.h"
#include <QtWidgets>
#include <algorithm>

// "Your projects" on Home (T164): one card for each project, with its versions as small tabs. A project is a folder in the
// Projects folder; its versions are the .mlt files in it (the main cut and the linked versions made at other sizes, which
// are named "<main> - <name>.mlt"). A click on the card opens the newest version; a click on a tab opens that one. Files of
// tests (under the tests folder of the install) are left out of the recent list. Its menu (the ... button, or a right-click)
// has "Make a Look from" each finished video of the project (T202): the person picks the version by clicking it.
class HomeVideos : public QScrollArea
{
public:
    struct Version
    {
        QString path;
        QString label;
        QDateTime modified;
    };
    struct Project
    {
        QString key;
        QString name;
        QList<Version> versions; // newest first
        QDateTime newest;
    };

    explicit HomeVideos(QWidget *parent) : QScrollArea(parent)
    {
        setObjectName(QStringLiteral("welcomeVideos"));
        setWidgetResizable(true);
        setFrameShape(QFrame::NoFrame);
        // letitedit (T383): as low as one row of cards (it scrolls) on a short screen, so Home fits 1024x768 and 1366x768
        setMinimumHeight(190);
        setMaximumHeight(332);
        setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        m_body = new QWidget(this);
        m_body->setStyleSheet(QStringLiteral("background: transparent;"));
        m_grid = new QGridLayout(m_body);
        m_grid->setContentsMargins(0, 0, 8, 0);
        m_grid->setSpacing(10);
        setWidget(m_body);
        viewport()->setStyleSheet(QStringLiteral("background: transparent;"));
        setStyleSheet(QStringLiteral("QScrollArea { background: transparent; border: none; }"));
        m_pool.setMaxThreadCount(1);
    }

    ~HomeVideos() override { m_pool.waitForDone(); }

    int count() const { return m_projects.size(); }
    const QList<Project> &projects() const { return m_projects; }

    // is this file one of a test's? (not in the Projects folder this window uses, but under the install's tests folder)
    static bool isTestPath(const QString &path)
    {
        const QString tests = QDir::cleanPath(aiRootPath(QStringLiteral("tests"))) + QLatin1Char('/');
        const QString clean = QDir::cleanPath(path);
        const QString projects = QDir::cleanPath(Settings.videoProjectsFolder()) + QLatin1Char('/');
        return clean.startsWith(tests, Qt::CaseInsensitive) && !clean.startsWith(projects, Qt::CaseInsensitive);
    }

    static QString versionLabel(const QFileInfo &file, const QString &projectName)
    {
        QString label = file.completeBaseName();
        if (label.startsWith(projectName, Qt::CaseInsensitive)) {
            label = label.mid(projectName.size());
            label.remove(QRegularExpression(QStringLiteral("^[\\s\\-_:]+")));
        }
        if (label.isEmpty())
            return QObject::tr("Main");
        return label.left(1).toUpper() + label.mid(1);
    }

    void refresh()
    {
        const QDir root(Settings.videoProjectsFolder());
        QStringList paths;
        for (const QString &recent : Settings.recent())
            if (!isTestPath(recent))
                paths << recent;
        for (const auto &file : root.entryInfoList({QStringLiteral("*.mlt")}, QDir::Files))
            paths << file.absoluteFilePath();
        for (const auto &folder : root.entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot))
            for (const auto &file : QDir(folder.absoluteFilePath()).entryInfoList({QStringLiteral("*.mlt")}, QDir::Files))
                paths << file.absoluteFilePath();
        QMap<QString, Project> byKey;
        QSet<QString> seen;
        for (const auto &path : paths) {
            const QFileInfo file(path);
            const QString key = file.canonicalFilePath().toCaseFolded();
            if (!file.isFile() || (file.suffix().toLower() != QLatin1String("mlt") && file.suffix().toLower() != QLatin1String("xml"))
                || seen.contains(key))
                continue;
            seen.insert(key);
            // a file in a folder of the Projects folder belongs to that folder's project; any other file is its own project
            const QString folder = file.absolutePath();
            const bool inProject = QDir::cleanPath(QFileInfo(folder).absolutePath()).compare(QDir::cleanPath(root.absolutePath()), Qt::CaseInsensitive) == 0
                                   && QDir::cleanPath(folder).compare(QDir::cleanPath(root.absolutePath()), Qt::CaseInsensitive) != 0;
            const QString projectKey = inProject ? folder : file.absoluteFilePath();
            Project &project = byKey[projectKey];
            project.key = projectKey;
            project.name = inProject ? QFileInfo(folder).fileName() : file.completeBaseName();
            project.versions.append({file.absoluteFilePath(), QString(), file.lastModified()});
        }
        QList<Project> projects;
        for (Project project : std::as_const(byKey)) {
            std::sort(project.versions.begin(), project.versions.end(), [](const Version &left, const Version &right) {
                return left.modified == right.modified ? left.path < right.path : left.modified > right.modified;
            });
            for (Version &version : project.versions)
                version.label = versionLabel(QFileInfo(version.path), project.name);
            project.newest = project.versions.first().modified;
            projects << project;
        }
        std::sort(projects.begin(), projects.end(), [](const Project &left, const Project &right) {
            return left.newest == right.newest ? left.key < right.key : left.newest > right.newest;
        });
        QString signature;
        for (const auto &project : projects)
            for (const auto &version : project.versions)
                signature += version.path + QString::number(version.modified.toMSecsSinceEpoch());
        if (signature == m_signature)
            return;
        m_signature = signature;
        m_projects = projects;
        rebuild();
    }

protected:
    void resizeEvent(QResizeEvent *event) override
    {
        QScrollArea::resizeEvent(event);
        const int columns = columnCount();
        if (columns != m_columns && !m_projects.isEmpty())
            rebuild();
    }

private:
    int columnCount() const
    {
        return qMax(1, qMin(window()->width() >= 1600 ? 4 : 3, viewport()->width() / 230));
    }

    // one card; a click anywhere on it but a tab opens the newest version
    class Card : public QFrame
    {
    public:
        Card(const QString &newest, QWidget *parent) : QFrame(parent), m_newest(newest)
        {
            setCursor(Qt::PointingHandCursor);
        }

        QStringList versions; // the project's .mlt files, newest first (for its menu)

        // T202: "Make a Look from" each finished video of the project's versions, newest first; none yet: the offer to
        // export the newest version first
        void showMenu(const QPoint &at)
        {
            auto *menu = new QMenu(this);
            menu->setObjectName(QStringLiteral("welcomeProjectMenu"));
            menu->setAttribute(Qt::WA_DeleteOnClose);
            const QPointer<Card> guard(this);
            int shown = 0;
            for (const QString &version : std::as_const(versions)) {
                for (const QFileInfo &video : LearnLooks::finishedVideos(version)) {
                    if (shown++ >= 8)
                        break;
                    const QString path = video.absoluteFilePath();
                    auto *action = menu->addAction(tr("Make a Look from “%1”").arg(video.completeBaseName()));
                    action->setObjectName(QStringLiteral("welcomeLookFromVideo_%1").arg(shown - 1));
                    action->setToolTip(QDir::toNativeSeparators(path));
                    connect(action, &QAction::triggered, this, [guard, version, path]() {
                        QMetaObject::invokeMethod(&MAIN, [guard, version, path]() {
                            LearnLooks::startFromProject(&MAIN, version, path, guard ? static_cast<QWidget *>(guard) : &MAIN);
                        }, Qt::QueuedConnection);
                    });
                }
            }
            if (!shown && !versions.isEmpty()) {
                const QString newest = versions.first();
                auto *action = menu->addAction(tr("Make a Look from this video…"));
                action->setObjectName(QStringLiteral("welcomeLookFromVideo_none"));
                connect(action, &QAction::triggered, this, [guard, newest]() {
                    QMetaObject::invokeMethod(&MAIN, [guard, newest]() {
                        LearnLooks::offerFromProject(&MAIN, newest, guard ? static_cast<QWidget *>(guard) : &MAIN);
                    }, Qt::QueuedConnection);
                });
            }
            menu->popup(at);
        }

    protected:
        void contextMenuEvent(QContextMenuEvent *event) override { showMenu(event->globalPos()); }

        void mouseReleaseEvent(QMouseEvent *event) override
        {
            QFrame::mouseReleaseEvent(event);
            if (event->button() == Qt::LeftButton && rect().contains(event->position().toPoint())) {
                const QString path = m_newest;
                QMetaObject::invokeMethod(&MAIN, [path]() { MAIN.openHomeVideo(path); }, Qt::QueuedConnection);
            }
        }

    private:
        QString m_newest;
    };

    void rebuild()
    {
        while (auto item = m_grid->takeAt(0)) {
            if (auto widget = item->widget()) {
                widget->hide();
                widget->deleteLater();
            }
            delete item;
        }
        m_columns = columnCount();
        int index = 0;
        for (const Project &project : std::as_const(m_projects)) {
            auto *card = new Card(project.versions.first().path, m_body);
            for (const Version &version : project.versions)
                card->versions << version.path;
            card->setObjectName(QStringLiteral("welcomeProject_%1").arg(index));
            card->setProperty("project", project.name);
            card->setStyleSheet(QStringLiteral("QFrame#%1 { border: 1px solid #36414b; border-radius: 8px; background: transparent; }"
                                               "QFrame#%1:hover { background: #283842; }")
                                    .arg(card->objectName()));
            card->setToolTip(project.key);
            auto *column = new QVBoxLayout(card);
            column->setContentsMargins(8, 8, 8, 8);
            column->setSpacing(4);
            auto *picture = new QLabel(card);
            picture->setObjectName(QStringLiteral("welcomeProjectPicture_%1").arg(index));
            picture->setFixedSize(178, 100);
            picture->setAlignment(Qt::AlignCenter);
            picture->setPixmap(QIcon(QStringLiteral(":/icons/letitedit/letitedit_lockup_dark-bg.svg")).pixmap(QSize(178, 100)));
            picture->setAttribute(Qt::WA_TransparentForMouseEvents);
            column->addWidget(picture, 0, Qt::AlignHCenter);
            auto *title = new QLabel(project.name, card);
            title->setObjectName(QStringLiteral("welcomeProjectTitle_%1").arg(index));
            title->setStyleSheet(QStringLiteral("font-weight: 600; background: transparent; border: none;"));
            title->setAttribute(Qt::WA_TransparentForMouseEvents);
            title->setText(title->fontMetrics().elidedText(project.name, Qt::ElideRight, 200));
            column->addWidget(title);
            auto *when = new QLabel(tr("Edited %1").arg(QLocale().toString(project.newest.date(), QLocale::ShortFormat)), card);
            when->setObjectName(QStringLiteral("welcomeProjectDate_%1").arg(index));
            when->setStyleSheet(QStringLiteral("color: #a9b0b5; font-size: 11px; background: transparent; border: none;"));
            when->setAttribute(Qt::WA_TransparentForMouseEvents);
            column->addWidget(when);
            auto *tabs = new QHBoxLayout;
            tabs->setSpacing(4);
            int tabIndex = 0;
            for (const Version &version : project.versions) {
                if (tabIndex >= 4)
                    break;
                auto *tab = new QPushButton(version.label, card);
                tab->setObjectName(QStringLiteral("welcomeVersion_%1_%2").arg(index).arg(tabIndex));
                tab->setProperty("path", version.path);
                tab->setFlat(true);
                tab->setCursor(Qt::PointingHandCursor);
                tab->setToolTip(tr("Open %1").arg(QDir::toNativeSeparators(version.path)));
                tab->setStyleSheet(QStringLiteral("QPushButton { font-size: 10px; padding: 1px 8px; border-radius: 9px; border: 1px solid %1; color: %2; background: %3; }"
                                                  "QPushButton:hover { color: #ffffff; border-color: #2A8597; }")
                                       .arg(tabIndex == 0 ? QStringLiteral("#2A8597") : QStringLiteral("#36414b"),
                                            tabIndex == 0 ? QStringLiteral("#ffffff") : QStringLiteral("#a9b0b5"),
                                            tabIndex == 0 ? QStringLiteral("#203b42") : QStringLiteral("transparent")));
                const QString path = version.path;
                connect(tab, &QPushButton::clicked, this, [path]() {
                    QMetaObject::invokeMethod(&MAIN, [path]() { MAIN.openHomeVideo(path); }, Qt::QueuedConnection);
                });
                tabs->addWidget(tab);
                ++tabIndex;
            }
            tabs->addStretch(1);
            auto *more = new QToolButton(card);
            more->setObjectName(QStringLiteral("welcomeProjectMore_%1").arg(index));
            more->setText(QStringLiteral("⋯"));
            more->setAutoRaise(true);
            more->setCursor(Qt::PointingHandCursor);
            more->setToolTip(tr("More: make a Look from this video"));
            more->setAccessibleName(tr("More for %1").arg(project.name));
            connect(more, &QToolButton::clicked, card, [card, more]() { card->showMenu(more->mapToGlobal(QPoint(0, more->height()))); });
            tabs->addWidget(more);
            column->addLayout(tabs);
            m_grid->addWidget(card, index / m_columns, index % m_columns, Qt::AlignTop | Qt::AlignLeft);
            loadPicture(index, project.versions.first().path);
            ++index;
        }
        for (int c = 0; c <= m_columns; ++c)
            m_grid->setColumnStretch(c, c == m_columns ? 1 : 0); // the cards sit together on the left
        m_grid->setRowStretch(index / m_columns + 1, 1);
    }

    // the cover picture beside the project, else the first picture or frame of its media
    void loadPicture(int index, const QString &project)
    {
        const QPointer<HomeVideos> guard(this);
        m_pool.start(QRunnable::create([guard, index, project]() {
            QImage image;
            const QFileInfo file(project);
            const QString cover = file.dir().filePath(file.completeBaseName() + QStringLiteral(" thumbnail.jpg"));
            image.load(cover);
            if (image.isNull()) {
                QFile document(project);
                if (document.open(QIODevice::ReadOnly)) {
                    const QByteArray contents = document.readAll();
                    document.close();
                    QXmlStreamReader reader(contents);
                    QString base = file.absolutePath();
                    while (!reader.atEnd()) {
                        reader.readNext();
                        if (reader.isStartElement() && reader.name() == QLatin1String("mlt")) {
                            const QString root = reader.attributes().value(QStringLiteral("root")).toString();
                            if (!root.isEmpty())
                                base = root;
                        }
                        if (!reader.isStartElement() || reader.name() != QLatin1String("property")
                            || reader.attributes().value(QStringLiteral("name")) != QLatin1String("resource"))
                            continue;
                        const QString source = QDir(base).absoluteFilePath(reader.readElementText());
                        const QFileInfo media(source);
                        if (!media.isFile() || media.suffix().toLower() == QLatin1String("mlt")
                            || media.suffix().toLower() == QLatin1String("xml"))
                            continue;
                        if (!image.load(source)) {
                            Mlt::Profile profile;
                            Mlt::Producer producer(profile, source.toUtf8().constData());
                            producer.set("threads", 1);
                            if (producer.is_valid())
                                image = MLT.image(producer, qMin(30, qMax(0, producer.get_length() / 10)), 240, 130);
                        }
                        if (!image.isNull())
                            break;
                    }
                }
            }
            if (guard && !image.isNull())
                QMetaObject::invokeMethod(guard, [guard, index, image]() {
                    if (!guard)
                        return;
                    if (auto *label = guard->findChild<QLabel *>(QStringLiteral("welcomeProjectPicture_%1").arg(index)))
                        label->setPixmap(QPixmap::fromImage(image).scaled(178, 100, Qt::KeepAspectRatio, Qt::SmoothTransformation));
                }, Qt::QueuedConnection);
        }));
    }

    QWidget *m_body = nullptr;
    QGridLayout *m_grid = nullptr;
    QThreadPool m_pool;
    QString m_signature;
    QList<Project> m_projects;
    int m_columns = 0;
};

#endif
