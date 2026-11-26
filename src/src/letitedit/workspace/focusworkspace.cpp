/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit workspace: the brand look and the simple layout over the engine's docks, actions, models and AI commands,
 * which all stay native. One header row (wordmark, menus, project, undo/redo, Ask the AI, Export), steps down the
 * left in the order a video gets made (Media, Cut, Captions, Music, Effects, AI; Export video in the header), plain panel names, a welcome
 * screen instead of the engine's New Project form, and a timeline bar with the few commands people use.
 */

#include "letitedit/workspace/focusworkspace.h"

#include "actions.h"
#include "controllers/filtercontroller.h"
#include "docks/filtersdock.h"
#include "docks/encodedock.h"
#include "docks/playlistdock.h"
#include "docks/subtitlesdock.h"
#include "docks/timelinedock.h"
#include "letitedit/panels/hookpanel.h"
#include "mainwindow.h"
#include "letitedit/panels/musicpicker.h"
#include "player.h"
#include "settings.h"
#include "letitedit/home/welcomepage.h"
#include "widgets/newprojectfolder.h"
#include "widgets/statuslabelwidget.h"
#include "letitedit/workspace/studiotextpanel.h"

#include <QtWidgets>
#include <memory>

bool focusWorkspaceEnabled()
{
    return qEnvironmentVariable("LETITEDIT_WORKSPACE") != QStringLiteral("classic");
}

// letitedit's own line icons first (icons/letitedit/ui), the engine's theme icons for everything else.
QIcon focusWorkspaceIcon(const QString &name)
{
    const QString own = QStringLiteral(":/icons/letitedit/ui/%1.svg").arg(name);
    if (QFile::exists(own))
        return QIcon(own);
    return QIcon::fromTheme(name, QIcon(QStringLiteral(":/icons/%1/32x32/%2.png").arg(QIcon::themeName(), name)));
}

void applyFocusPalette()
{
    if (!focusWorkspaceEnabled())
        return;
    using namespace LetItEditColors;
#if QT_VERSION >= QT_VERSION_CHECK(6, 8, 0)
    qApp->styleHints()->setColorScheme(Qt::ColorScheme::Dark);
#endif
    qApp->setProperty("focusWorkspace", true);
    QIcon::setThemeName(QStringLiteral("dark"));
    QPalette p = qApp->palette();
    p.setColor(QPalette::Window, QColor(ink));
    p.setColor(QPalette::Base, QColor(panel));
    p.setColor(QPalette::AlternateBase, QColor("#243036"));
    p.setColor(QPalette::Button, QColor(raised));
    p.setColor(QPalette::Light, QColor(lifted));
    p.setColor(QPalette::Midlight, QColor(lifted));
    p.setColor(QPalette::Mid, QColor(line));
    p.setColor(QPalette::Dark, QColor(deep));
    p.setColor(QPalette::Shadow, QColor(deep));
    p.setColor(QPalette::WindowText, QColor(cream));
    p.setColor(QPalette::Text, QColor(cream));
    p.setColor(QPalette::ButtonText, QColor(cream));
    p.setColor(QPalette::BrightText, QColor("#FFFFFF"));
    p.setColor(QPalette::PlaceholderText, QColor(muted));
    p.setColor(QPalette::Highlight, QColor(teal));
    p.setColor(QPalette::HighlightedText, QColor(cream));
    p.setColor(QPalette::Link, QColor(rust));
    p.setColor(QPalette::LinkVisited, QColor(rustDeep));
    p.setColor(QPalette::ToolTipBase, QColor(panel));
    p.setColor(QPalette::ToolTipText, QColor(cream));
    p.setColor(QPalette::Disabled, QPalette::Text, QColor(dim));
    p.setColor(QPalette::Disabled, QPalette::WindowText, QColor(dim));
    p.setColor(QPalette::Disabled, QPalette::ButtonText, QColor(dim));
    qApp->setPalette(p);
}

class FocusWorkspace : public QObject
{
public:
    explicit FocusWorkspace(MainWindow *window)
        : QObject(window)
        , m_window(window)
        , m_settings(Settings.appDataLocation() + QStringLiteral("/focus-workspace.ini"), QSettings::IniFormat)
    {
        setObjectName(QStringLiteral("focusWorkspace"));
        m_window->setProperty("focusWorkspace", true);
        m_window->setProperty("focusWorkspaceVersion", 4);
        m_window->setDockOptions(QMainWindow::AllowTabbedDocks | QMainWindow::AllowNestedDocks);
        m_window->setTabPosition(Qt::AllDockWidgetAreas, QTabWidget::North);
        installStyle();
        installTextPanel();
        m_window->subtitlesDock()->installStudioPresentation();
        if (auto exportDock = qobject_cast<EncodeDock *>(dock("EncodeDock")))
            exportDock->installStudioPresentation();
        HookPanel::install(m_window);
        installDockHeaders();
        installHeader();
        installRail();
        installRailHandle();
        installWorkspaceMenu();
        m_window->playlistDock()->installFocusPresentation();
        installTimelineControls();
        installPreviewWords();
        installWelcome();
        simplifyChat();
        installLiveMode();
        installQaActions();
        m_window->installEventFilter(this);
        connect(m_window, &MainWindow::aboutToShutDown, this, [this]() { saveLayout(); });
        connect(m_window, &QWidget::windowTitleChanged, this, [this]() { updateProject(); });
        connect(m_window->undoStack(), &QUndoStack::cleanChanged, this, [this]() { updateProject(); });
        connect(m_window, &MainWindow::producerOpened, this, [this]() {
            updateProject();
            if (m_welcome)
                m_welcome->hide(); // a video or clip is open: the player shows it
            welcomeShown(false);
        });
        const QByteArray saved = m_settings.value(QStringLiteral("layout-v4")).toByteArray();
        if (saved.isEmpty() || !m_window->restoreState(saved, 4)) {
            resetLayout();
        } else {
            m_category = m_settings.value(QStringLiteral("category"), QStringLiteral("media")).toString();
            if (!m_categories.contains(m_category))
                m_category = QStringLiteral("media");
            syncNavigation();
        }
        if (auto original = m_window->findChild<QToolBar *>(QStringLiteral("mainToolBar")))
            original->hide();
        updateProject();
        QTimer::singleShot(350, this, [this]() { updateResponsiveLayout(); });
        // the timeline was hidden when the window last closed: AI-live again, once the window has its size
        if (!m_settings.value(QStringLiteral("timeline-shown"), true).toBool())
            QTimer::singleShot(600, this, [this]() { setTimelineShown(false); });
        QTimer::singleShot(0, this, [this]() { welcomeShown(m_welcome && m_welcome->isVisible()); });
    }

protected:
    bool eventFilter(QObject *watched, QEvent *event) override
    {
        if (watched == m_window && event->type() == QEvent::Resize) {
            // Reflow at breakpoints; never shrink type or numeric fields to fit.
            updateResponsiveLayout();
        } else if (watched == m_window && event->type() == QEvent::KeyPress
                   && static_cast<QKeyEvent *>(event)->key() == Qt::Key_Escape && m_window->isFullScreen()) {
            Actions["actionEnterFullScreen"]->trigger();
            return true;
        } else if (watched == m_window && event->type() == QEvent::WindowStateChange) {
            if (m_exitFullScreenAction)
                m_exitFullScreenAction->setVisible(m_window->isFullScreen());
        } else if (watched == m_engineStart && m_welcome) {
            // The engine shows its New Project form whenever no video is open; the welcome screen takes its place.
            if (event->type() == QEvent::Show) {
                QTimer::singleShot(0, this, [this]() {
                    if (m_engineStart && m_engineStart->isVisible()) {
                        m_swapping = true;
                        m_engineStart->hide();
                        m_swapping = false;
                        m_welcome->show();
                        welcomeShown(true);
                    }
                });
            } else if (event->type() == QEvent::Hide && !m_swapping) {
                m_welcome->hide();
                welcomeShown(false);
            }
        }
        return QObject::eventFilter(watched, event);
    }

private:
    QDockWidget *dock(const char *name) const
    {
        return m_window->findChild<QDockWidget *>(QString::fromLatin1(name));
    }

    QAction *action(const QString &name, const QString &title, const std::function<void()> &handler)
    {
        auto a = new QAction(title, m_window);
        a->setObjectName(name);
        m_window->addAction(a);
        Actions.add(name, a, tr("Focus"));
        connect(a, &QAction::triggered, this, handler);
        return a;
    }

    QToolButton *button(QToolBar *bar, const QString &text, const QString &iconName,
                        QAction *existing = nullptr)
    {
        auto b = new QToolButton(bar ? static_cast<QWidget *>(bar) : static_cast<QWidget *>(m_window));
        b->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        b->setFocusPolicy(Qt::StrongFocus);
        b->setAutoRaise(true);
        if (existing) {
            if (existing->icon().isNull() && !iconName.isEmpty())
                existing->setIcon(focusWorkspaceIcon(iconName));
            b->setDefaultAction(existing);
            // Override only this button's label, never the underlying command or shortcut.
            b->setText(text);
            m_window->addAction(existing);
            connect(existing, &QAction::changed, b, [b, text]() { b->setText(text); });
        } else {
            b->setText(text);
        }
        if (!iconName.isEmpty())
            b->setIcon(focusWorkspaceIcon(iconName));
        b->setAccessibleName(text);
        if (bar)
            bar->addWidget(b);
        return b;
    }

    void installStyle()
    {
        using namespace LetItEditColors;
        const QString css = QStringLiteral(R"CSS(
            QMainWindow { background: %ink%; }
            QMainWindow::separator { width: 6px; height: 6px; background: %ink%; }
            QMainWindow::separator:hover { background: %line%; }
            QToolBar#focusHeader { background: %ink%; border: none; border-bottom: 1px solid %line%; padding: 6px 10px; spacing: 6px; }
            QToolBar#focusHeader QToolButton { background: %raised%; border: 1px solid #3A4248; border-radius: 8px; padding: 7px 11px; color: %cream%; font-weight: 600; min-height: 18px; }
            QToolBar#focusHeader QToolButton:hover { background: %lifted%; border-color: #4A545B; }
            QToolBar#focusHeader QToolButton:pressed { background: %deep%; }
            QToolBar#focusHeader QToolButton:disabled { color: %dim%; background: %panel%; }
            QToolBar#focusHeader QToolButton#focusMenuButton { background: transparent; border-color: transparent; color: #CFC9BE; font-weight: 500; }
            QToolBar#focusHeader QToolButton#focusMenuButton:hover { background: %raised%; color: %cream%; }
            QToolBar#focusHeader QToolButton#focusMenuButton::menu-indicator { image: none; }
            QToolBar#focusHeader QToolButton[focusAccent="teal"] { border-color: %teal%; color: %tealLight%; }
            QToolBar#focusHeader QToolButton[focusAccent="teal"]:hover { background: %tealDeep%; color: %cream%; }
            QToolBar#focusHeader QToolButton[focusAccent="teal"]:checked { background: %tealDeep%; color: %cream%; }
            QToolBar#focusHeader QToolButton[focusPrimary="true"] { background: %rust%; border-color: %rust%; color: #101416; }
            QToolBar#focusHeader QToolButton[focusPrimary="true"]:hover { background: %rustLight%; border-color: %rustLight%; }
            QToolBar#focusHeader QToolButton[focusPrimary="true"]:pressed { background: %rustDeep%; }
            QLabel#focusBrand { padding: 0 8px 0 2px; }
            QLabel#focusProject { color: %cream%; font-weight: 600; padding: 0 2px 0 10px; }
            QLabel#focusSaved { color: %muted%; font-size: 12px; padding: 0 10px 0 6px; }
            QToolBar#focusRail { background: #121619; border: none; border-right: 1px solid %line%; padding: 8px 6px; spacing: 4px; }
            QToolBar#focusRail QToolButton { background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 9px 2px 7px 2px; min-width: 64px; max-width: 64px; color: %muted%; font-size: 11px; font-weight: 600; }
            QToolBar#focusRail QToolButton:hover { background: %raised%; color: %cream%; }
            QToolBar#focusRail QToolButton:checked { background: %tealDeep%; color: %cream%; }
            QToolBar#focusRail QToolButton[focusRailAi="true"] { border: 1px dashed #3A4248; }
            QToolBar#focusRail QToolButton[focusRailAi="true"]:checked { border-color: %teal%; }
            QToolButton:focus, QPushButton:focus { border: 1px solid %teal%; }
            QDockWidget { border: none; titlebar-close-icon: url(:/icons/dark/32x32/window-close.png); }
            QWidget[focusDockHeader="true"] { background: %panel%; border-bottom: 1px solid %line%; }
            QWidget[focusDockHeader="true"] QLabel { padding: 8px 2px; font-weight: 700; font-size: 14px; background: transparent; border: none; }
            QWidget[focusDockHeader="true"] QToolButton { border: none; border-radius: 4px; padding: 4px; }
            QWidget[focusDockHeader="true"] QToolButton:hover { background: %raised%; }
            QTabBar::tab { padding: 8px 12px; border: none; border-bottom: 2px solid transparent; background: %panel%; color: %muted%; }
            QTabBar::tab:selected { border-bottom-color: %rust%; color: %cream%; }
            QTabBar::tab:hover { color: %cream%; }
            QPushButton { background: %raised%; border: 1px solid #3A4248; border-radius: 8px; padding: 7px 12px; color: %cream%; }
            QPushButton:hover { background: %lifted%; border-color: #4A545B; }
            QPushButton:pressed { background: %deep%; }
            QPushButton:checked { background: %tealDeep%; border-color: %teal%; }
            QPushButton:disabled { color: %dim%; background: %panel%; border-color: %line%; }
            QPushButton[studioPrimary="true"] { background: %rust%; color: #101416; border-color: %rust%; font-weight: 600; }
            QPushButton[studioPrimary="true"]:hover { background: %rustLight%; border-color: %rustLight%; }
            QPushButton[studioPrimary="true"]:pressed { background: %rustDeep%; }
            QPushButton[studioPrimary="true"]:disabled { background: #5A3A2C; color: #CFC9BE; border-color: #5A3A2C; }
            QPushButton[studioChoice="true"] { padding-left: 6px; padding-right: 6px; }
            QPushButton[studioChoice="true"]:checked { background: %tealDeep%; border-color: %teal%; }
            QPushButton#focusMediaImport { background: %rust%; border-color: %rust%; color: #FFFFFF; font-weight: 600; }
            QPushButton#focusMediaImport:hover { background: %rustLight%; }
            QToolButton { border-radius: 4px; }
            QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser { border: 1px solid %line%; border-radius: 6px; padding: 5px; background: %panel%; color: %cream%; selection-background-color: %teal%; }
            QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus { border-color: %teal%; }
            QAbstractSpinBox { border: 1px solid %line%; border-radius: 6px; padding: 3px 5px; background: %panel%; }
            QAbstractSpinBox QLineEdit { border: none; border-radius: 0; padding: 0; background: transparent; }
            QComboBox { border: 1px solid %line%; border-radius: 6px; padding: 6px 10px; background: %panel%; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView { background: %panel%; border: 1px solid %line%; selection-background-color: %tealDeep%; }
            QToolButton[aiChatChoice="true"] { border: 1px solid %line%; border-radius: 6px; padding: 5px 8px; background: %panel%; color: %cream%; }
            QToolButton[aiChatChoice="true"]:hover { background: %raised%; border-color: #4A545B; }
            QMenu { background: %panel%; border: 1px solid %line%; padding: 6px; }
            QMenu::item { padding: 7px 24px 7px 12px; border-radius: 6px; }
            QMenu::item:selected { background: %tealDeep%; color: %cream%; }
            QMenu::separator { height: 1px; background: %line%; margin: 5px 8px; }
            QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
            QScrollBar::handle:vertical { background: %line%; min-height: 24px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #4A545B; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background: #30383C; height: 15px; margin: 0; }
            QScrollBar::handle:horizontal { background: %teal%; min-width: 36px; border-radius: 6px; }
            QScrollBar::handle:horizontal:hover { background: %rust%; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QStatusBar { color: %muted%; background: #121619; border-top: 1px solid %line%; font-size: 12px; }
            QStatusBar QLabel { color: %muted%; }
            QStatusBar QPushButton { background: transparent; border: none; border-radius: 0; color: %muted%; padding: 2px 6px; text-align: left; }
            QStatusBar QPushButton:hover { color: %cream%; }
            QToolTip { background: %panel%; color: %cream%; border: 1px solid %line%; padding: 6px; }
            QTreeView, QListView, QTableView { background: %panel%; alternate-background-color: #222A2E; border: none; selection-background-color: %tealDeep%; selection-color: %cream%; }
            QHeaderView::section { background: %panel%; border: none; border-bottom: 1px solid %line%; padding: 6px; color: %muted%; }
            QCheckBox, QRadioButton { spacing: 7px; }
            QGroupBox { border: 1px solid %line%; border-radius: 8px; margin-top: 10px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: %muted%; }
            QWidget#Player { background: %ink%; }
            QWidget#focusPreviewCanvas { background: %deep%; }
            QLabel#focusMediaHelp, QLabel#focusMediaEmpty { color: %muted%; }
            QToolButton#focusPreviewOptions { padding: 5px 8px; }
            QToolBar#focusTimelineControls { background: #121619; border: none; border-bottom: 1px solid %line%; padding: 4px 10px; spacing: 6px; }
            QToolBar#focusTimelineControls QToolButton { padding: 6px 10px; border: 1px solid transparent; border-radius: 7px; min-height: 18px; color: %cream%; }
            QToolBar#focusTimelineControls QToolButton:hover { background: %raised%; border-color: #3A4248; }
            QToolBar#focusTimelineControls QToolButton:checked { background: %tealDeep%; border-color: %teal%; color: %cream%; }
            QToolBar#focusTimelineControls QToolButton[focusQuiet="true"] { color: %muted%; }
            QLabel[studioHeading="true"] { font-size: 16px; font-weight: 700; color: %cream%; }
            QLabel[studioMuted="true"] { color: %muted%; }
            QPlainTextEdit#studioTextContent { padding: 10px; border-radius: 9px; font-size: 15px; }
            QToolButton#studioExportMore { padding: 7px; border: 1px solid %line%; border-radius: 8px; }
            QWidget#welcomePage { background: %ink%; }
            QLabel#welcomeHeading { font-size: 24px; font-weight: 700; color: %cream%; padding-top: 6px; }
            QLabel#welcomeLead { color: %muted%; font-size: 14px; }
            QPushButton#welcomeAi { background: transparent; border: none; color: %muted%; padding: 4px 0; text-align: left; }
            QPushButton#welcomeAi[connected="true"] { color: %ok%; }
            QPushButton#welcomeAi[aiState="attention"] { color: #E8A060; }
            QPushButton#welcomeAiTest { padding: 4px 10px; }
            QLabel#welcomePrivacy { color: %muted%; font-size: 12px; }
            QPushButton#welcomeAi:hover { color: %tealLight%; }
            QLabel#welcomeRecentTitle { color: %cream%; font-weight: 700; }
            QListWidget#welcomeRecent { background: transparent; color: %muted%; font-size: 13px; }
            QListWidget#welcomeRecent::item { padding: 5px 4px; border-radius: 6px; }
            QListWidget#welcomeRecent::item:hover { background: %raised%; color: %cream%; }
            QPushButton[welcomeCard="true"] { background: %panel%; border: 1px solid %line%; border-radius: 12px; padding: 0; text-align: left; }
            QPushButton[welcomeCard="true"]:hover { background: %raised%; border-color: #4A545B; }
            QPushButton[welcomeCard="true"][welcomeFirst="true"] { border-color: %rust%; }
            QPushButton[welcomeCard="true"][welcomeFirst="true"]:hover { background: #2A2320; }
            QLabel#welcomeCardIcon { background: %tealDeep%; border-radius: 10px; }
            QLabel#welcomeCardIcon[welcomeFirst="true"] { background: %rust%; }
            QLabel#welcomeCardTitle { font-size: 15px; font-weight: 700; color: %cream%; }
            QLabel#welcomeCardText { font-size: 12px; color: %muted%; }
            QLabel#welcomeCardHint { font-size: 11px; color: %dim%; }
            QSlider::groove:horizontal { height: 4px; background: %line%; border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: %cream%; }
            QSlider::sub-page:horizontal { background: %teal%; border-radius: 2px; }
            QProgressBar { border: none; background: %line%; border-radius: 4px; height: 8px; text-align: center; color: transparent; }
            QProgressBar::chunk { background: %rust%; border-radius: 4px; }
        )CSS");
        QString out = css;
        const QList<QPair<QString, const char *>> tokens = {
            {QStringLiteral("%ink%"), ink}, {QStringLiteral("%panel%"), panel}, {QStringLiteral("%raised%"), raised},
            {QStringLiteral("%lifted%"), lifted}, {QStringLiteral("%line%"), line}, {QStringLiteral("%deep%"), deep},
            {QStringLiteral("%cream%"), cream}, {QStringLiteral("%muted%"), muted}, {QStringLiteral("%dim%"), dim},
            {QStringLiteral("%rustLight%"), rustLight}, {QStringLiteral("%rustDeep%"), rustDeep}, {QStringLiteral("%rust%"), rust},
            {QStringLiteral("%tealDeep%"), tealDeep}, {QStringLiteral("%tealLight%"), tealLight}, {QStringLiteral("%teal%"), teal},
            {QStringLiteral("%ok%"), ok}};
        for (const auto &t : tokens)
            out.replace(t.first, QString::fromLatin1(t.second));
        m_window->setStyleSheet(out);
        if (auto status = m_window->player()->findChild<StatusLabelWidget *>()) {
            // Progress and file messages belong in the application status bar;
            // a long file path must never impose a minimum preview width.
            status->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
            status->setMinimumWidth(0);
            m_window->statusBar()->addWidget(status, 1);
            // The engine styles this as a teal pill over the player; in the status bar it is plain words.
            status->setStyleSheet(QStringLiteral("QWidget { background: transparent; color: %1; border-radius: 0; } "
                                                 "QPushButton { border: none; padding: 2px 6px; text-align: left; }")
                                      .arg(QString::fromLatin1(muted)));
        }
        if (m_window->player()->layout())
            m_window->player()->layout()->setContentsMargins(12, 6, 12, 8);
        m_window->statusBar()->setSizeGripEnabled(false);
        m_window->statusBar()->show();
        m_window->statusBar()->showMessage(tr("Ready"), 4000);
    }

    void installTextPanel()
    {
        auto d = new QDockWidget(tr("Captions & text"), m_window);
        d->setObjectName(QStringLiteral("focusTextDock"));
        auto body = new QWidget(d);
        auto column = new QVBoxLayout(body);
        column->setContentsMargins(0, 0, 0, 0);
        column->setSpacing(0);
        auto scroll = new QScrollArea(d);
        scroll->setWidgetResizable(true);
        scroll->setFrameShape(QFrame::NoFrame);
        auto text = new StudioTextPanel(m_window, scroll);
        scroll->setWidget(text);
        column->addWidget(scroll, 1);
        auto footer = new QHBoxLayout;
        footer->setContentsMargins(12, 10, 12, 12);
        footer->setSpacing(6);
        footer->addWidget(text->primaryButton(), 1);
        footer->addWidget(text->newButton());
        column->addLayout(footer);
        d->setWidget(body);
        m_window->addDockWidget(Qt::LeftDockWidgetArea, d);
        d->hide();
        connect(d, &QDockWidget::visibilityChanged, text, [text](bool visible) {
            if (visible)
                text->readSelection();
        });
        connect(m_window->timelineDock(), &TimelineDock::selected, this, [this, text](Mlt::Producer *producer) {
            if (m_preview || !producer || !producer->is_valid()
                || m_window->timelineDock()->selection().size() != 1)
                return;
            const QString service = QString::fromUtf8(producer->get("mlt_service"));
            if (!producer->get_int("shotcut:studioText") && service != QStringLiteral("color")
                && service != QStringLiteral("colour"))
                return;
            for (int i = 0; i < producer->filter_count(); ++i) {
                std::unique_ptr<Mlt::Filter> filter(producer->filter(i));
                if (filter && QString::fromUtf8(filter->get(kShotcutFilterProperty)) == QStringLiteral("dynamicText")) {
                    // T99: with the AI open, selecting text is how a request begins, so the AI stays where it is.
                    auto chat = dock("aiChatDock");
                    if (m_categories.contains(QStringLiteral("captions")) && m_category != QStringLiteral("captions")
                        && !(chat && chat->isVisible()))
                        showCategory(QStringLiteral("captions"));
                    text->readSelection();
                    break;
                }
            }
        });
    }

    // The one name each beginner panel goes by: its title, its tab when panels share a place, the Workspace menu. The
    // effects panel is "Picture effects" in the Look step and "Sound settings" in the Music step.
    static QMap<QString, QString> publicNames()
    {
        return {{QStringLiteral("PlaylistDock"), tr("Media")},
                {QStringLiteral("FilesDock"), tr("Browse files")},
                {QStringLiteral("propertiesDock"), tr("Inspector")},
                {QStringLiteral("FiltersDock"), tr("Picture effects")},
                {QStringLiteral("SubtitlesDock"), tr("Caption lines")},
                {QStringLiteral("focusTextDock"), tr("Captions")},
                {QStringLiteral("TimelineDock"), tr("Timeline")},
                {QStringLiteral("EncodeDock"), tr("Export video")},
                {QStringLiteral("focusHookDock"), tr("Opening")},
                {QStringLiteral("aiAudioLibraryDock"), tr("Music")},
                {QStringLiteral("stickersDock"), tr("Elements")}};
    }

    // A panel's public name, on its title and its tab; kept when the engine (or a dock change) puts its own back.
    void setPublicName(QDockWidget *d, const QString &name)
    {
        if (!d || name.isEmpty())
            return;
        d->setProperty("letitedit:publicName", name);
        if (d->windowTitle() != name)
            d->setWindowTitle(name);
        if (d->titleBarWidget())
            if (auto label = d->titleBarWidget()->findChild<QLabel *>(QStringLiteral("focusDockTitle")))
                label->setText(name);
    }

    void installDockHeaders()
    {
        QMap<QString, QString> names = publicNames();
        names.insert(QStringLiteral("aiChatDock"), tr("AI")); // its title names the AI (Chat with Claude)
        const QMap<QString, QString> publicName = publicNames();
        for (auto d : m_window->findChildren<QDockWidget *>()) {
            const QString title = names.value(d->objectName(), d->windowTitle());
            auto header = new QWidget(d);
            header->setProperty("focusDockHeader", true);
            header->setObjectName(QStringLiteral("focusTitle_") + d->objectName());
            auto row = new QHBoxLayout(header);
            row->setContentsMargins(14, 2, 8, 2);
            row->setSpacing(6);
            auto label = new QLabel(title, header);
            label->setObjectName(QStringLiteral("focusDockTitle"));
            label->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
            row->addWidget(label);
            if (d == dock("FilesDock")) {
                auto add = new QToolButton(header);
                add->setIcon(focusWorkspaceIcon(QStringLiteral("add")));
                add->setToolTip(tr("Add media files"));
                add->setAccessibleName(tr("Add media files"));
                row->addWidget(add);
                connect(add, &QToolButton::clicked, this, [this]() { importMedia(); });
            }
            if (d != m_window->timelineDock()) {
                auto close = new QToolButton(header);
                close->setIcon(focusWorkspaceIcon(QStringLiteral("close")));
                close->setToolTip(tr("Close panel"));
                close->setAccessibleName(tr("Close %1").arg(title));
                row->addWidget(close);
                connect(close, &QToolButton::clicked, d, &QWidget::hide);
            }
            d->setTitleBarWidget(header);
            if (publicName.contains(d->objectName())) {
                setPublicName(d, publicName.value(d->objectName()));
                connect(d, &QWidget::windowTitleChanged, this, [this, d](const QString &title) {
                    const QString name = d->property("letitedit:publicName").toString();
                    if (!name.isEmpty() && title != name)
                        QTimer::singleShot(0, this, [this, d, name]() { setPublicName(d, name); });
                });
            }
        }
    }

    // One row: the wordmark, a Menu button with the engine's menus, the project and its saved state, undo/redo,
    // Ask the AI, Export. The menu bar itself stays (menus are looked up through it) but hidden.
    void buildHeaderMenu()
    {
        auto bar = m_window->findChild<QMenuBar *>(QStringLiteral("menuBar"));
        if (!bar)
            bar = m_window->menuBar();
        bar->setNativeMenuBar(false);
        bar->hide();
        m_menuBar = bar;
        m_header = new QToolBar(tr("letitedit header"), m_window);
        m_header->setObjectName(QStringLiteral("focusHeader"));
        m_header->setMovable(false);
        m_header->setFloatable(false);
        m_header->setAllowedAreas(Qt::TopToolBarArea);
        m_header->setIconSize(QSize(16, 16));
        m_window->addToolBar(Qt::TopToolBarArea, m_header);
        auto brand = new QLabel(m_header);
        brand->setObjectName(QStringLiteral("focusBrand"));
        brand->setPixmap(QIcon(QStringLiteral(":/icons/letitedit/letitedit_logo_dark-bg.svg")).pixmap(QSize(70, 28)));
        brand->setAccessibleName(QStringLiteral("letitedit"));
        brand->setToolTip(QStringLiteral("letitedit"));
        m_header->addWidget(brand);
        auto menuButton = new QToolButton(m_header);
        menuButton->setObjectName(QStringLiteral("focusMenuButton"));
        menuButton->setText(tr("Menu"));
        menuButton->setIcon(focusWorkspaceIcon(QStringLiteral("more")));
        menuButton->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
        menuButton->setPopupMode(QToolButton::InstantPopup);
        menuButton->setToolTip(tr("Everything else: files, editing, view, playback, settings, help"));
        auto all = new QMenu(menuButton);
        for (auto a : bar->actions()) {
            if (a->menu())
                all->addMenu(a->menu());
        }
        menuButton->setMenu(all);
        m_menuButton = menuButton;
        // A hidden menu bar would silence its actions' shortcuts (Ctrl+S, Space, ...): give every menu action to
        // the window itself, so the keys keep working with the bar out of sight.
        std::function<void(QMenu *)> adopt = [&](QMenu *menu) {
            for (auto a : menu->actions()) {
                if (a->menu())
                    adopt(a->menu());
                else if (!a->isSeparator() && !a->shortcut().isEmpty())
                    m_window->addAction(a);
            }
        };
        for (auto a : bar->actions()) {
            if (a->menu())
                adopt(a->menu());
        }
        m_header->addWidget(menuButton);
    }

    void installHeader()
    {
        buildHeaderMenu();
        m_exitFullScreen = button(m_header, tr("Exit full screen"), QStringLiteral("close"),
                                  Actions["actionEnterFullScreen"]);
        m_exitFullScreen->setObjectName(QStringLiteral("focusExitFullScreen"));
        m_exitFullScreen->setToolTip(tr("Leave full screen (Esc)"));
        for (auto *a : m_header->actions())
            if (m_header->widgetForAction(a) == m_exitFullScreen)
                m_exitFullScreenAction = a;
        if (m_exitFullScreenAction)
            m_exitFullScreenAction->setVisible(m_window->isFullScreen());
        auto *escapeFullScreen = new QShortcut(QKeySequence(Qt::Key_Escape), m_window);
        escapeFullScreen->setContext(Qt::WidgetWithChildrenShortcut);
        connect(escapeFullScreen, &QShortcut::activated, this, [this]() {
            // T99: Esc clears what's selected in the video first
            if (auto preview = m_window->findChild<PreviewObjects *>(); preview && preview->escapePressed())
                return;
            if (m_window->isFullScreen())
                Actions["actionEnterFullScreen"]->trigger();
        });
        if (auto newVideo = Actions["makeFirstCutAction"]) {
            auto b = button(m_header, tr("New video"), QStringLiteral("new"), newVideo);
            b->setObjectName(QStringLiteral("focusNewVideoButton"));
            b->setAutoRaise(false);
            b->setToolTip(tr("Start a new video from a folder of footage: say what you're making, pick a style, and "
                             "your AI makes the first cut"));
            m_responsiveButtons.append(b);
            m_primaryButtons.append(b);
        }
        m_project = new QLabel(m_header);
        m_project->setObjectName(QStringLiteral("focusProject"));
        m_projectAction = m_header->addWidget(m_project);
        m_saved = new QLabel(tr("Saved"), m_header);
        m_saved->setObjectName(QStringLiteral("focusSaved"));
        m_savedAction = m_header->addWidget(m_saved);
        auto spring = new QWidget(m_header);
        spring->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
        m_header->addWidget(spring);
        m_headerSpring = spring;
        auto undo = m_window->undoStack()->createUndoAction(m_window);
        auto redo = m_window->undoStack()->createRedoAction(m_window);
        for (auto pair : {qMakePair(undo, QStringLiteral("undo")), qMakePair(redo, QStringLiteral("redo"))}) {
            auto b = button(m_header, pair.first->text(), pair.second, pair.first);
            b->setAutoRaise(false);
            b->setToolButtonStyle(Qt::ToolButtonIconOnly);
            b->setToolTip(pair.first == undo ? tr("Undo") : tr("Redo"));
        }
        m_timelineAction = action(QStringLiteral("focusTimelineAction"), tr("Show Timeline"), [this]() {
            setTimelineShown(!m_timelineShown);
        });
        m_timelineAction->setCheckable(true);
        m_timelineAction->setChecked(true);
        m_timelineAction->setToolTip(tr("Show or hide the timeline. Hidden, you edit by talking to your AI and marking "
                                        "up the video full screen (Review)."));
        auto timelineButton = button(m_header, tr("Timeline"), QStringLiteral("timeline"), m_timelineAction);
        timelineButton->setObjectName(QStringLiteral("focusTimelineButton"));
        timelineButton->setAutoRaise(false);
        timelineButton->setProperty("focusAccent", QStringLiteral("teal"));
        timelineButton->setToolTip(m_timelineAction->toolTip());
        m_responsiveButtons.append(timelineButton);
        m_secondaryButtons.append(timelineButton);
        if (auto reviewAction = Actions["reviewModeAction"]) {
            auto review = button(m_header, tr("Review"), QStringLiteral("review"), reviewAction);
            review->setObjectName(QStringLiteral("focusReviewButton"));
            review->setAutoRaise(false);
            review->setToolTip(tr("Watch full screen, draw on the picture and say what should change; your AI "
                                  "re-edits from your notes (Ctrl+Shift+R)"));
            m_responsiveButtons.append(review);
            m_primaryButtons.append(review);
        }
        auto ai = action(QStringLiteral("focusAssistantAction"), tr("Ask the AI"), [this]() {
            leavePreview();
            auto d = dock("aiChatDock");
            if (!d)
                return;
            if (d->isVisible())
                d->hide();
            else
                showRight(d);
        });
        ai->setCheckable(true);
        if (auto chat = dock("aiChatDock"))
            connect(chat, &QDockWidget::visibilityChanged, ai, &QAction::setChecked);
        auto askAi = button(m_header, tr("Ask the AI"), QStringLiteral("ai"), ai);
        askAi->setAutoRaise(false);
        askAi->setProperty("focusAccent", QStringLiteral("teal"));
        askAi->setToolTip(tr("Talk to your AI about this video: it edits with you, every change one Undo step"));
        m_responsiveButtons.append(askAi);
        m_secondaryButtons.append(askAi);
        auto finishAction = action(QStringLiteral("focusExportAction"), tr("Export video"), [this]() {
            leavePreview();
            showRight(dock("EncodeDock"));
        });
        auto finish = button(m_header, tr("Export video"), QStringLiteral("export"), finishAction);
        finish->setAutoRaise(false);
        finish->setProperty("focusPrimary", true);
        finish->setToolTip(tr("Save the finished video as a file for YouTube, Shorts, TikTok, Reels or anywhere"));
        m_exportButton = finish;
        m_responsiveButtons.append(finish);
        m_primaryButtons.append(finish);
        m_headerRight = m_header;
        action(QStringLiteral("focusImportAction"), tr("Add media"), [this]() { importMedia(); });
        action(QStringLiteral("focusAdjustAction"), tr("Inspector"), [this]() { toggleInspector(); })->setCheckable(true);
        if (auto properties = dock("propertiesDock"))
            connect(properties, &QDockWidget::visibilityChanged, Actions["focusAdjustAction"], &QAction::setChecked);
        action(QStringLiteral("focusPreviewAction"), tr("Preview only"), [this]() { togglePreview(); })->setCheckable(true);
    }

    // The steps down the left, in the order a video gets made.
    void installRail()
    {
        m_nav = new QToolBar(tr("Steps"), m_window);
        m_nav->setObjectName(QStringLiteral("focusRail"));
        m_nav->setMovable(false);
        m_nav->setFloatable(false);
        m_nav->setAllowedAreas(Qt::LeftToolBarArea);
        m_nav->setIconSize(QSize(24, 24));
        m_window->addToolBar(Qt::LeftToolBarArea, m_nav);
        const QList<QStringList> entries = {
            {QStringLiteral("media"), tr("Media"), QStringLiteral("media"), tr("Your clips, photos and sounds")},
            {QStringLiteral("cut"), tr("Cut"), QStringLiteral("cut"), tr("Trim, split and arrange on the timeline")},
            {QStringLiteral("captions"), tr("Captions"), QStringLiteral("captions"), tr("Captions of what is said, titles and text")},
            {QStringLiteral("music"), tr("Music"), QStringLiteral("music"), tr("Music, sound effects and the mix")},
            {QStringLiteral("look"), tr("Effects"), QStringLiteral("look"), tr("Color, effects and the picture")}};
        for (const auto &entry : entries) {
            auto a = action(QStringLiteral("focus%1Action").arg(entry[0]), entry[1], [this, key = entry[0]]() { showCategory(key); });
            a->setCheckable(true);
            auto b = button(m_nav, entry[1], entry[2], a);
            b->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
            b->setToolTip(entry[3]);
            m_categories.insert(entry[0], a);
        }
        // Export video has one place, the header. This older action stays for anything that still names it: it opens and
        // closes the same panel.
        auto share = action(QStringLiteral("focusshareAction"), tr("Export video"), [this]() {
            leavePreview();
            auto d = dock("EncodeDock");
            if (d && d->isVisible())
                d->hide();
            else
                showRight(d);
        });
        share->setCheckable(true);
        if (auto d = dock("EncodeDock"))
            connect(d, &QDockWidget::visibilityChanged, share, &QAction::setChecked);
        auto spring = new QWidget(m_nav);
        spring->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Expanding);
        m_nav->addWidget(spring);
        // The rail shows one place at a time (syncNavigation), so this has its own check mark; it opens the same chat.
        m_railAi = action(QStringLiteral("focusRailAiAction"), tr("AI"), [this]() {
            if (auto a = Actions["focusAssistantAction"])
                a->trigger();
            syncNavigation();
        });
        m_railAi->setCheckable(true);
        auto aiButton = button(m_nav, tr("AI"), QStringLiteral("ai"), m_railAi);
        aiButton->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
        aiButton->setProperty("focusRailAi", true);
        aiButton->setToolTip(tr("Talk to your AI about this video"));
        action(QStringLiteral("studioCaptionsAction"), tr("Caption lines"), [this]() {
            leavePreview();
            showCategory(QStringLiteral("captions"));
            auto captions = m_window->subtitlesDock();
            if (auto text = dock("focusTextDock")) {
                m_window->addDockWidget(Qt::LeftDockWidgetArea, captions);
                m_window->tabifyDockWidget(text, captions);
            }
            captions->show();
            captions->raise();
        });
    }

    void installRailHandle()
    {
        m_railHandle = new QToolBar(tr("Show steps"), m_window);
        m_railHandle->setObjectName(QStringLiteral("focusRailHandle"));
        m_railHandle->setMovable(false);
        m_railHandle->setFloatable(false);
        m_window->addToolBar(Qt::LeftToolBarArea, m_railHandle);
        auto *open = new QToolButton(m_railHandle);
        open->setObjectName(QStringLiteral("focusShowSteps"));
        open->setText(tr("☰  Show steps"));
        open->setToolButtonStyle(Qt::ToolButtonTextOnly);
        open->setMinimumHeight(36);
        open->setStyleSheet(QStringLiteral("QToolButton { border: 1px solid #2A8597; border-radius: 6px; "
                                           "padding: 6px 8px; background: #183840; color: #F4EFE6; font-weight: 600; } "
                                           "QToolButton:hover { background: #24505A; }"));
        open->setToolTip(tr("Show the steps"));
        open->setAccessibleName(tr("Show the steps"));
        connect(open, &QToolButton::clicked, this, [this]() {
            m_railCollapsed = false;
            if (!m_timelineShown)
                setTimelineShown(true);
            else
                m_nav->show();
            m_railHandle->hide();
        });
        m_railHandle->addWidget(open);
        m_railHandle->hide();
    }

    void installWorkspaceMenu()
    {
        auto view = m_window->findChild<QMenu *>(QStringLiteral("menuView"));
        if (!view)
            return;
        view->addSeparator();
        auto workspace = view->addMenu(tr("Workspace"));
        workspace->addAction(action(QStringLiteral("focusResetAction"), tr("Reset the layout"), [this]() { resetLayout(); }));
        workspace->addAction(action(QStringLiteral("focusToggleStepsAction"), tr("Show or hide the steps"), [this]() {
            m_railCollapsed = m_nav->isVisible();
            m_nav->setVisible(!m_railCollapsed);
            m_railHandle->setVisible(m_railCollapsed);
        }));
        workspace->addAction(Actions["focusPreviewAction"]);
        workspace->addAction(Actions["focusAdjustAction"]);
        if (auto files = dock("FilesDock"))
            workspace->addAction(tr("Browse files on this computer"), files, [this, files]() {
                leavePreview();
                m_window->addDockWidget(Qt::LeftDockWidgetArea, files);
                files->show();
                files->raise();
            });
        workspace->addAction(action(QStringLiteral("focusMaximizeAction"), tr("Fit the window to the screen"), [this]() {
            if (m_window->isMaximized())
                m_window->showNormal();
            else
                m_window->showMaximized();
        }));
        workspace->addSeparator();
        for (auto d : m_window->findChildren<QDockWidget *>())
            workspace->addAction(d->toggleViewAction());
    }

    void importMedia()
    {
        leavePreview();
        showCategory(QStringLiteral("media"));
        // The native import path handles playlists, metadata, proxies and undo.
        Actions["playlistAddFilesAction"]->trigger();
    }

    void installTimelineControls()
    {
        auto timeline = m_window->timelineDock();
        timeline->setMinimumHeight(210);
        auto old = timeline->findChild<QToolBar *>();
        if (!old || !timeline->widget() || !timeline->widget()->layout())
            return;
        auto bar = new QToolBar(tr("Timeline controls"), timeline);
        bar->setObjectName(QStringLiteral("focusTimelineControls"));
        bar->setMovable(false);
        bar->setFloatable(false);
        bar->setIconSize(QSize(17, 17));
        // One heading/command row instead of two stacked bars above the edit.
        timeline->setTitleBarWidget(new QWidget(timeline));
        auto title = new QLabel(tr("Timeline"), bar);
        title->setStyleSheet(QStringLiteral("font-weight: 700; font-size: 14px; padding-right: 12px;"));
        bar->addWidget(title);
        button(bar, tr("Split here"), QStringLiteral("split"), Actions["timelineSplitAction"])
            ->setToolTip(tr("Cut the clip under the playhead in two (S)"));
        button(bar, tr("Delete"), QStringLiteral("delete"), Actions["timelineDeleteAction"])
            ->setToolTip(tr("Remove the selected clip and close the gap"));
        button(bar, tr("Remove pauses"), QStringLiteral("pauses"), Actions["removePausesAction"])
            ->setToolTip(tr("Cut the silences and ums out of the talking"));
        button(bar, tr("Add music"), QStringLiteral("music"), Actions["addMusicAction"])
            ->setToolTip(tr("Pick a song from the free library, fitted under the talking"));
        if (auto hook = Actions["hookPanelAction"])
            button(bar, tr("New hook"), QStringLiteral("hook"), hook)
                ->setToolTip(tr("Try other openings for this video, one click each (one Undo step each)"));
        if (auto scene = Actions["makeCodeSceneAction"]) {
            auto sceneButton = button(bar, tr("Make a scene"), QStringLiteral("ai"), scene);
            sceneButton->setObjectName(QStringLiteral("focusMakeScene"));
            sceneButton->setToolTip(tr("Describe a scene for this moment; your AI draws it live on the timeline"));
        }
        if (auto images = Actions["imageGeneratorAction"]) {
            auto imagesButton = button(bar, tr("Image generator"), QStringLiteral("ai"), images);
            imagesButton->setObjectName(QStringLiteral("focusImageGenerator"));
            imagesButton->setToolTip(tr("Describe a picture; your AI has it made and keeps it with this video"));
        }
        if (auto layer = Actions["timelineAddAdjustmentLayerAction"]) {
            auto layerButton = button(bar, tr("Adjustment layer"), QStringLiteral("view-filter"), layer);
            layerButton->setObjectName(QStringLiteral("focusAdjustmentLayer"));
            layerButton->setToolTip(tr("A block whose effects change everything below it in the stack, for as long as it lasts"));
        }
        auto snap = button(bar, tr("Snap"), QStringLiteral("snap"), Actions["timelineSnapAction"]);
        snap->setProperty("focusQuiet", true);
        snap->setToolTip(tr("Clips snap to each other and to the playhead"));
        auto more = button(bar, tr("More"), QStringLiteral("more"));
        more->setProperty("focusQuiet", true);
        for (auto candidate : old->findChildren<QToolButton *>()) {
            if (candidate->menu()) {
                more->setMenu(candidate->menu());
                more->setPopupMode(QToolButton::InstantPopup);
                break;
            }
        }
        auto spring = new QWidget(bar);
        spring->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
        bar->addWidget(spring);
        if (auto zoom = old->findChild<QSlider *>()) {
            zoom->setMaximumWidth(145);
            zoom->setMinimumWidth(70);
            zoom->setToolTip(tr("Zoom the timeline"));
            bar->addWidget(zoom);
        }
        button(bar, tr("Fit"), QStringLiteral("fit"), Actions["timelineZoomFitAction"])
            ->setToolTip(tr("Show the whole video"));
        // Keep the original toolbar and its signals alive, while presenting a smaller set.
        timeline->widget()->layout()->setMenuBar(bar);
        old->hide();
    }

    // The preview's tabs say what is shown in plain words.
    void installPreviewWords()
    {
        auto player = m_window->player();
        if (auto tabs = player->findChild<QTabBar *>()) {
            if (tabs->count() >= 2) {
                tabs->setTabText(0, tr("A clip"));
                tabs->setTabText(1, tr("Your video"));
                tabs->setTabToolTip(0, tr("Look at one clip before it goes into the video"));
                tabs->setTabToolTip(1, tr("The video as it is cut right now"));
            }
        }
        for (auto label : player->findChildren<QLabel *>()) {
            if (label->text() == tr("Preview")) {
                label->setText(tr("Showing"));
                label->setStyleSheet(QStringLiteral("color: %1; font-weight: 600; padding: 6px 2px;").arg(QString::fromLatin1(LetItEditColors::muted)));
            }
        }
    }

    // The welcome screen stands in for the engine's New Project form whenever no video is open.
    void installWelcome()
    {
        auto player = m_window->player();
        m_engineStart = player->findChild<NewProjectFolder *>();
        if (!m_engineStart || !m_engineStart->parentWidget())
            return;
        auto parentLayout = qobject_cast<QBoxLayout *>(m_engineStart->parentWidget()->layout());
        if (!parentLayout)
            return;
        m_welcome = new WelcomePage(m_window, m_engineStart->parentWidget());
        const int index = parentLayout->indexOf(m_engineStart);
        parentLayout->insertWidget(index + 1, m_welcome, 10);
        m_welcome->hide();
        m_engineStart->installEventFilter(this);
        if (m_engineStart->isVisible() || !m_engineStart->isHidden()) {
            m_swapping = true;
            m_engineStart->hide();
            m_swapping = false;
            m_welcome->show();
            QTimer::singleShot(0, this, [this]() { welcomeShown(m_welcome && m_welcome->isVisible()); });
        }
    }

    // With nothing open there is nothing on the timeline: it folds away while the welcome screen shows, so the whole
    // start fits a laptop screen (1366x768), and comes back when a video opens.
    void welcomeShown(bool shown)
    {
        auto timeline = m_window->timelineDock();
        if (shown) {
            if (!m_homeActive) {
                m_homeActive = true;
                m_homeLayout = m_window->saveState(4);
                m_timelineFolded = m_timelineShown && timeline->isVisible() && !m_preview;
                // The player has no content yet. Keep only the invitation (or its progress view).
                for (auto *widget : m_window->player()->findChildren<QWidget *>(QString(), Qt::FindDirectChildrenOnly)) {
                    if (widget != m_welcome && widget != m_engineStart && !widget->isHidden()) {
                        m_homePlayerWidgets.append(widget);
                        widget->hide();
                    }
                }
                for (auto *dockWidget : m_window->findChildren<QDockWidget *>())
                    dockWidget->hide();
                for (auto *a : m_header->actions()) {
                    auto *widget = m_header->widgetForAction(a);
                    if (widget && widget != m_menuButton && widget != m_headerSpring
                        && widget->objectName() != QLatin1String("focusBrand")) {
                        m_homeHeaderActions.append(a);
                        a->setVisible(false);
                    }
                }
                if (m_nav)
                    m_nav->hide();
                if (m_railHandle)
                    m_railHandle->hide();
                // T383: without the editing panels Home needs less room: a window that ran past a small screen fits now
                QTimer::singleShot(0, m_window, [w = m_window]() { w->fitWindowToScreen(); });
            }
        } else {
            if (m_homeActive) {
                m_homeActive = false;
                bool anyDock = false;
                for (auto *dockWidget : m_window->findChildren<QDockWidget *>())
                    anyDock |= dockWidget->isVisible();
                if (!anyDock && m_timelineShown && !m_homeLayout.isEmpty())
                    m_window->restoreState(m_homeLayout, 4);
                for (auto widget : m_homePlayerWidgets)
                    if (widget)
                        widget->show();
                m_homePlayerWidgets.clear();
                for (auto a : m_homeHeaderActions)
                    if (a && a != m_exitFullScreenAction)
                        a->setVisible(true);
                m_homeHeaderActions.clear();
                if (m_exitFullScreenAction)
                    m_exitFullScreenAction->setVisible(m_window->isFullScreen());
                if (m_timelineShown && m_nav && !m_railCollapsed)
                    m_nav->show();
                if (m_railCollapsed && m_railHandle)
                    m_railHandle->show();
            }
            if (m_timelineFolded) {
                m_timelineFolded = false;
                if (m_timelineShown && !m_preview) {
                    timeline->show();
                    timeline->raise();
                }
            }
            if (!m_timelineShown) {
                timeline->hide();
                if (m_liveBar)
                    m_liveBar->show();
                if (m_railHandle && !m_railCollapsed)
                    m_railHandle->show();
            }
            m_homeLayout.clear();
        }
        updateProject();
    }

    void simplifyChat()
    {
        auto chat = dock("aiChatDock");
        if (!chat || !chat->widget())
            return;
        auto column = qobject_cast<QVBoxLayout *>(chat->widget()->layout());
        if (!column || column->count() < 3)
            return;
        auto controls = qobject_cast<QHBoxLayout *>(column->itemAt(column->count() - 1)->layout());
        if (!controls || controls->count() < 3)
            return;
        auto status = controls->takeAt(0);
        auto talk = controls->takeAt(0);
        auto voice = new QHBoxLayout;
        voice->addItem(status);
        voice->addItem(talk);
        column->insertLayout(column->count() - 1, voice); // above the buttons, under the typing box
        // The same filmstrip stays with the AI conversation after a project
        // opens, including Review's re-edit requests.
        auto *progressCard = new QWidget(chat->widget());
        progressCard->setObjectName(QStringLiteral("chatProgress"));
        auto *progressLayout = new QVBoxLayout(progressCard);
        progressLayout->setContentsMargins(4, 4, 4, 4);
        progressLayout->setSpacing(2);
        auto *progressLabel = new QLabel(tr("Getting ready..."), progressCard);
        progressLabel->setObjectName(QStringLiteral("chatProgressText"));
        progressLabel->setAlignment(Qt::AlignCenter);
        progressLayout->addWidget(progressLabel);
        auto *progressArt = new ProgressView(progressCard);
        progressLayout->addWidget(progressArt);
        auto *progressRange = new QLabel(progressCard);   // what is happening now (T193: no time-left guess)
        progressRange->setWordWrap(true);
        progressRange->setObjectName(QStringLiteral("chatProgressRange"));
        progressRange->setAlignment(Qt::AlignCenter);
        progressRange->setStyleSheet(QStringLiteral("color:#9ED6E2; font-weight:600;"));
        progressLayout->addWidget(progressRange);
        auto *progressSoFar = new QLabel(progressCard);
        progressSoFar->setObjectName(QStringLiteral("chatProgressSoFar"));
        progressSoFar->setAlignment(Qt::AlignCenter);
        progressSoFar->setWordWrap(true);
        progressSoFar->setProperty("studioMuted", true);
        progressLayout->addWidget(progressSoFar);
        column->insertWidget(1, progressCard);
        auto *finishedReview = new QLabel(chat->widget());
        finishedReview->setObjectName(QStringLiteral("chatFinishedReview"));
        finishedReview->setWordWrap(true);
        finishedReview->setAlignment(Qt::AlignCenter);
        finishedReview->setOpenExternalLinks(true);
        column->insertWidget(2, finishedReview);
        progressCard->hide();
        // T202: "Make a Look from this video" under the chat once the open project's newest finished video is done: New
        // video has just finished it, or its review says ready. The person clicks it; nothing is asked.
        auto *lookRow = new QWidget(chat->widget());
        lookRow->setObjectName(QStringLiteral("chatLookFromVideo"));
        auto *lookLayout = new QHBoxLayout(lookRow);
        lookLayout->setContentsMargins(4, 2, 4, 2);
        auto *lookText = new QLabel(lookRow);
        lookText->setObjectName(QStringLiteral("chatLookFromVideoText"));
        lookText->setWordWrap(true);
        lookText->setProperty("studioMuted", true);
        lookLayout->addWidget(lookText, 1);
        auto *lookButton = new QPushButton(tr("Make a Look from this video"), lookRow);
        lookButton->setObjectName(QStringLiteral("chatLookFromVideoButton"));
        lookLayout->addWidget(lookButton);
        column->insertWidget(2, lookRow);
        lookRow->hide();
        struct LookOffer
        {
            QString project, video;
            QSet<QString> used; // videos a Look was asked for from this row
            int tick = 0;
        };
        auto offer = std::make_shared<LookOffer>();
        connect(lookButton, &QPushButton::clicked, lookRow, [this, offer, lookRow]() {
            if (offer->video.isEmpty())
                return;
            if (LearnLooks::startFromProject(m_window, offer->project, offer->video, m_window)) {
                offer->used.insert(offer->video);
                lookRow->hide();
            }
        });
        auto updateLookOffer = [this, offer, lookRow, lookText](const QJsonObject &progress, bool working) {
            if (working) {
                lookRow->hide();
                return;
            }
            if (offer->tick++ % 5) // every few seconds: it reads the project's folder
                return;
            const QString project = m_window->fileName();
            const QFileInfoList videos = project == m_window->untitledFileName() ? QFileInfoList() : LearnLooks::finishedVideos(project);
            const QString video = videos.isEmpty() ? QString() : videos.first().absoluteFilePath();
            bool done = false;
            QString why;
            if (!video.isEmpty() && !offer->used.contains(video)) {
                const QFileInfo shown(project);
                bool madeHere = progress.value(QStringLiteral("outcome")).toString() == QLatin1String("done");
                if (madeHere) {
                    madeHere = false;
                    for (const QJsonValue &made : progress.value(QStringLiteral("projects")).toArray())
                        madeHere = madeHere || QFileInfo(made.toString()).canonicalFilePath() == shown.canonicalFilePath();
                }
                const QFileInfo finished(video);
                const QJsonObject review = QJsonDocument::fromJson([&]() {
                    QFile file(finished.dir().filePath(finished.completeBaseName() + QStringLiteral(" review/review.json")));
                    return file.open(QIODevice::ReadOnly) ? file.readAll() : QByteArray();
                }()).object();
                const bool ready = review.value(QStringLiteral("verdict")).toString().compare(QLatin1String("ready"), Qt::CaseInsensitive) == 0;
                done = madeHere || ready;
                why = ready ? tr("“%1” passed its review.").arg(finished.completeBaseName())
                            : tr("“%1” is finished.").arg(finished.completeBaseName());
            }
            offer->project = project;
            offer->video = done ? video : QString();
            lookText->setText(why + QLatin1Char(' ') + tr("Like how it came out? Keep it as a Look to reuse."));
            lookRow->setVisible(done && !lookRow->parentWidget()->isHidden());
        };
        auto *progressTimer = new QTimer(progressCard);
        progressTimer->setInterval(700);
        connect(progressTimer, &QTimer::timeout, progressCard, [this, progressCard, progressLabel, progressArt, progressRange, progressSoFar,
                                                                updateLookOffer, finishedReview]() {
            const QJsonObject chat = aiChatState();
            const QJsonObject progress = progressRecord(progressRunOf(chat));   // this window's own run (T193)
            syncProgressWaiting(progress, chat, aiChatSettings().value(QStringLiteral("python")).toString(),
                                aiRootPath(QStringLiteral("bridge/progress_feed.py")));
            const ProgressState display = progressState(progress, chat);
            finishedReview->setText(progressFinishedText(progress));
            finishedReview->setVisible(!chat.value(QStringLiteral("busy")).toBool() && !finishedReview->text().isEmpty());
            updateLookOffer(progress, display.visible || chat.value(QStringLiteral("busy")).toBool());
            // One account of the work: the home screen has it while it's showing, so the chat doesn't repeat it. The
            // filmstrip needs more height than a laptop's panel has to spare (the window would grow off the screen).
            const bool onHome = m_welcome && m_welcome->isVisible();
            // before the card shows: it would push the window taller. A note has no steps to show (T221).
            progressArt->setVisible(m_window->height() >= 900 && !display.note);
            progressCard->setVisible(display.visible && !onHome && !progressCard->parentWidget()->isHidden());
            if (!display.visible)
                return;
            progressLabel->setText(display.label);
            progressRange->setText(display.now);
            progressRange->setVisible(!display.now.isEmpty());
            const QString soFar = display.done.isEmpty() ? display.soFar : display.done + QStringLiteral("\n") + display.soFar;
            progressSoFar->setText(soFar.trimmed());
            progressSoFar->setVisible(!soFar.trimmed().isEmpty());
            progressArt->setProgress(display.step / 6.0, display.step);
        });
        progressTimer->start();
        column->setContentsMargins(12, 10, 12, 12);
        column->setSpacing(9);
        controls->insertStretch(0, 1);
        for (auto b : chat->findChildren<QPushButton *>()) {
            b->setSizePolicy(QSizePolicy::Minimum, QSizePolicy::Fixed);
            if (b->text() == QStringLiteral("Send"))
                b->setProperty("studioPrimary", true);
        }
        chat->setMinimumWidth(320);
    }

    void showRight(QDockWidget *d)
    {
        if (!d)
            return;
        for (auto other : m_window->findChildren<QDockWidget *>()) {
            if (other != d && m_window->dockWidgetArea(other) == Qt::RightDockWidgetArea)
                other->hide();
        }
        m_window->addDockWidget(Qt::RightDockWidgetArea, d);
        d->show();
        d->raise();
        m_window->resizeDocks({d}, {qMin(440, qMax(360, m_window->width() / 3))}, Qt::Horizontal);
        updateResponsiveLayout();
    }

    void showCategory(const QString &category)
    {
        if (!m_timelineShown)
            setTimelineShown(true); // a step of the timeline layout was asked for
        leavePreview();
        if (m_window->width() < 1440) {
            for (auto d : m_window->findChildren<QDockWidget *>()) {
                if (m_window->dockWidgetArea(d) == Qt::RightDockWidgetArea)
                    d->hide();
            }
            m_suppressedLeft.clear();
        }
        m_category = category;
        for (auto d : m_window->findChildren<QDockWidget *>()) {
            if (m_window->dockWidgetArea(d) == Qt::LeftDockWidgetArea)
                d->hide();
        }
        auto model = m_window->filterController()->metadataModel();
        model->setSearch(QString());
        model->setFilter(MetadataModel::NoFilter);
        QDockWidget *target = nullptr;
        if (category == QStringLiteral("media")) {
            target = dock("PlaylistDock");
        } else if (category == QStringLiteral("cut")) {
            target = nullptr; // the timeline has the whole width
        } else if (category == QStringLiteral("captions")) {
            target = dock("focusTextDock");
        } else if (category == QStringLiteral("music")) {
            target = dock("aiAudioLibraryDock");
            auto effects = dock("FiltersDock");
            setPublicName(qobject_cast<QDockWidget *>(effects), tr("Sound settings"));
            model->setFilter(MetadataModel::AudioFilter);
            if (target && effects) {
                m_window->addDockWidget(Qt::LeftDockWidgetArea, target);
                m_window->addDockWidget(Qt::LeftDockWidgetArea, effects);
                m_window->tabifyDockWidget(target, effects);
                effects->show();
            }
        } else {
            target = dock("FiltersDock");
            setPublicName(target, tr("Picture effects"));
            model->setFilter(MetadataModel::VideoFilter);
            model->setSearch(QStringLiteral("#color"));
        }
        if (target) {
            if (m_window->dockWidgetArea(target) != Qt::LeftDockWidgetArea)
                m_window->addDockWidget(Qt::LeftDockWidgetArea, target);
            target->show();
            target->raise();
            m_window->resizeDocks({target}, {qBound(300, m_window->width() / 4, 380)}, Qt::Horizontal);
        }
        m_window->timelineDock()->show();
        m_timelineFolded = false; // a step was asked for: the timeline stays
        if (category == QStringLiteral("cut"))
            m_window->timelineDock()->setFocus();
        if (category == QStringLiteral("music"))
            MusicPicker::showMusicPanel(m_window); // filled and up to date, as from Add music
        m_window->setProperty("focusCategory", category);
        syncNavigation();
        QTimer::singleShot(0, this, [this]() { updateTabLabels(); });
    }

    void updateTabLabels()
    {
        // a safety net: the panels carry their public names themselves (setPublicName)
        const QMap<QString, QString> labels = {{tr("Playlist"), tr("Media")}, {tr("Files"), tr("Browse files")},
            {tr("Filters"), tr("Picture effects")}, {tr("Subtitles"), tr("Caption lines")}, {tr("Text"), tr("Captions")},
            {QStringLiteral("Music & sound"), tr("Music")}};
        // Label the visible tabs without renaming docks or their machine-facing identities.
        for (auto tabs : m_window->findChildren<QTabBar *>()) {
            for (int i = 0; i < tabs->count(); ++i) {
                const auto label = labels.constFind(tabs->tabText(i));
                if (label != labels.cend())
                    tabs->setTabText(i, label.value());
            }
        }
    }

    void syncNavigation()
    {
        // One "you are here" on the rail. A step whose panel isn't showing (it gave way to the panel on the right, or
        // hasn't been opened) isn't where you are.
        bool stepShown = m_category == QLatin1String("cut"); // the timeline is its panel
        for (auto d : m_window->findChildren<QDockWidget *>())
            stepShown |= d->isVisible() && !d->isFloating() && m_window->dockWidgetArea(d) == Qt::LeftDockWidgetArea;
        for (auto it = m_categories.cbegin(); it != m_categories.cend(); ++it)
            it.value()->setChecked(stepShown && it.key() == m_category);
        if (m_railAi) {
            auto chat = dock("aiChatDock");
            m_railAi->setChecked(!stepShown && chat && chat->isVisible());
        }
        m_window->setProperty("focusCategory", m_category);
    }

    void toggleInspector()
    {
        leavePreview();
        auto properties = dock("propertiesDock");
        if (properties && properties->isVisible()) {
            properties->hide();
            return;
        }
        showRight(properties);
    }

    void togglePreview()
    {
        if (m_preview) {
            leavePreview();
            return;
        }
        m_previewLayout = m_window->saveState(4);
        m_preview = true;
        for (auto d : m_window->findChildren<QDockWidget *>())
            d->hide();
        if (auto a = m_window->findChild<QAction *>(QStringLiteral("focusPreviewAction")))
            a->setChecked(true);
        m_window->setProperty("focusPreview", true);
    }

    void leavePreview()
    {
        if (!m_preview)
            return;
        m_preview = false;
        m_window->restoreState(m_previewLayout, 4);
        if (auto a = m_window->findChild<QAction *>(QStringLiteral("focusPreviewAction")))
            a->setChecked(false);
        m_window->setProperty("focusPreview", false);
    }

    void resetLayout()
    {
        leavePreview();
        if (!m_timelineShown) {
            m_timelineShown = true;
            m_timelineLayout.clear();
            if (m_liveBar)
                m_liveBar->hide();
            syncTimelineAction();
        }
        m_window->setUpdatesEnabled(false);
        for (auto d : m_window->findChildren<QDockWidget *>()) {
            d->setFloating(false);
            d->hide();
        }
        m_window->setCorner(Qt::BottomLeftCorner, Qt::BottomDockWidgetArea);
        m_window->setCorner(Qt::BottomRightCorner, Qt::BottomDockWidgetArea);
        m_window->addDockWidget(Qt::BottomDockWidgetArea, m_window->timelineDock());
        m_window->timelineDock()->show();
        m_window->timelineDock()->raise();
        showCategory(QStringLiteral("media"));
        m_window->resizeDocks({m_window->timelineDock()}, {qBound(230, m_window->height() / 3, 400)}, Qt::Vertical);
        // MainWindow restores its old geometry after construction. Apply the default
        // proportions once that has finished; later user splitter changes are kept.
        QTimer::singleShot(450, this, [this]() {
            if (!m_preview)
                m_window->resizeDocks({m_window->timelineDock()}, {qBound(230, m_window->height() / 3, 400)}, Qt::Vertical);
        });
        if (auto original = m_window->findChild<QToolBar *>(QStringLiteral("mainToolBar")))
            original->hide();
        m_nav->show();
        if (m_header)
            m_header->show();
        m_window->setUpdatesEnabled(true);
        m_window->statusBar()->showMessage(tr("Layout reset"), 2500);
    }

    void updateProject()
    {
        const bool hasProject = !m_window->fileName().isEmpty()
                                && m_window->fileName() != m_window->untitledFileName();
        const QString name = hasProject ? QFileInfo(m_window->fileName()).completeBaseName() : QString();
        m_project->setText(m_project->fontMetrics().elidedText(name, Qt::ElideMiddle, m_projectWidth));
        m_project->setToolTip(name);
        m_saved->setText(m_window->isWindowModified() ? tr("Unsaved changes") : tr("Saved"));
        m_projectAction->setVisible(hasProject);
        m_savedAction->setVisible(hasProject);
        if (!m_fitting)
            QTimer::singleShot(0, this, [this]() { fitHeader(); });
    }

    // The header row keeps its words as long as there is room for them, measured on the row itself: first the project
    // name gets shorter, then the saved state goes, then Timeline and Ask the AI show only their icons, then the name
    // goes, then Menu; New video, Review and Export keep their words longest.
    void fitHeader()
    {
        if (!m_header || !m_project || m_fitting)
            return;
        m_fitting = true;
        const auto room = [this]() {
            const QMargins m = m_header->contentsMargins();
            const int w = m_header->isVisible() && m_header->width() > 0 ? m_header->width() : m_window->width();
            return w - m.left() - m.right() - 24; // the row's own padding
        };
        const auto needed = [this]() {
            const int spacing = m_header->layout() ? qMax(0, m_header->layout()->spacing()) : 6;
            int w = 0;
            for (QAction *a : m_header->actions()) {
                QWidget *widget = m_header->widgetForAction(a);
                if (!a->isVisible() || !widget || widget == m_headerSpring)
                    continue;
                w += widget->sizeHint().width() + spacing;
            }
            return w;
        };
        const auto apply = [this](int level) {
            m_projectWidth = level >= 1 ? 150 : 320;
            const QString name = m_project->toolTip();
            m_project->setText(m_project->fontMetrics().elidedText(name, Qt::ElideMiddle, m_projectWidth));
            const bool hasProject = !m_window->fileName().isEmpty()
                                    && m_window->fileName() != m_window->untitledFileName();
            if (m_projectAction)
                m_projectAction->setVisible(hasProject && level < 4);
            if (m_savedAction)
                m_savedAction->setVisible(hasProject && level < 2);
            for (auto b : m_secondaryButtons)
                b->setToolButtonStyle(level >= 3 ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
            if (m_menuButton)
                m_menuButton->setToolButtonStyle(level >= 5 ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
            for (auto b : m_primaryButtons)
                b->setToolButtonStyle(level >= 6 ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
        };
        int level = 0;
        for (; level <= 6; ++level) {
            apply(level);
            if (needed() <= room())
                break;
        }
        m_header->setProperty("focusHeaderLevel", qMin(level, 6));
        if (m_homeActive)
            for (auto a : m_homeHeaderActions)
                if (a)
                    a->setVisible(false);
        for (auto b : m_responsiveButtons)
            b->setToolTip(b->toolTip().isEmpty() ? b->text() : b->toolTip());
        m_fitting = false;
    }

    void updateResponsiveLayout()
    {
        if (!m_headerRight || !m_project || m_resizing)
            return;
        m_resizing = true;
        // Below this width a step panel on the left and an Export or AI panel on the right would squeeze the preview.
        const bool compact = m_window->width() < 1440;
        fitHeader(); // the header's words follow the room the header really has
        bool hasRight = false;
        for (auto d : m_window->findChildren<QDockWidget *>())
            hasRight |= d->isVisible() && m_window->dockWidgetArea(d) == Qt::RightDockWidgetArea;
        if (!m_preview && compact && hasRight) {
            for (auto d : m_window->findChildren<QDockWidget *>()) {
                if (d->isVisible() && m_window->dockWidgetArea(d) == Qt::LeftDockWidgetArea) {
                    m_suppressedLeft = d;
                    d->hide();
                }
            }
        } else if (!m_preview && m_suppressedLeft) {
            m_suppressedLeft->show();
            m_suppressedLeft->raise();
            m_suppressedLeft.clear();
        }
        syncNavigation();
        m_resizing = false;
    }

    void installQaActions()
    {
        for (auto d : m_window->findChildren<QDockWidget *>())
            connect(d, &QDockWidget::visibilityChanged, this, [this]() {
                QTimer::singleShot(0, this, [this]() { updateResponsiveLayout(); });
            });
        // Test hooks use the existing QAction bridge and are absent from ordinary
        // launches. No transport method or MCP tool schema is added or changed.
        if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
            return;
        const QMap<QString, QSize> sizes = {{QStringLiteral("Small"), QSize(900, 620)}, {QStringLiteral("Compact"), QSize(1000, 660)},
            {QStringLiteral("Medium"), QSize(1280, 800)}, {QStringLiteral("Wide"), QSize(1600, 930)}};
        for (auto it = sizes.cbegin(); it != sizes.cend(); ++it)
            action(QStringLiteral("focusQa%1Action").arg(it.key()), it.key(), [this, size = it.value()]() {
                m_window->showNormal();
                m_window->resize(size);
                m_window->move(20, 20);
            });
        action(QStringLiteral("focusQaGeometryAction"), tr("Measure UI"), [this]() {
            QJsonArray fields;
            for (auto spin : m_window->findChildren<QAbstractSpinBox *>()) {
                if (!spin->isVisible())
                    continue;
                auto edit = spin->findChild<QLineEdit *>();
                if (!edit)
                    continue;
                const auto margins = edit->textMargins();
                fields.append(QJsonObject{{"class", QString::fromLatin1(spin->metaObject()->className())},
                    {"name", spin->objectName()}, {"text", edit->text()},
                    {"width", spin->width()}, {"height", spin->height()},
                    {"textWidth", edit->fontMetrics().horizontalAdvance(edit->text())},
                    {"availableWidth", edit->contentsRect().width() - margins.left() - margins.right()},
                    {"textHeight", edit->fontMetrics().height()},
                    {"availableHeight", edit->contentsRect().height() - margins.top() - margins.bottom()}});
            }
            QJsonArray docks;
            for (auto d : m_window->findChildren<QDockWidget *>()) {
                if (d->isVisible())
                    docks.append(QJsonObject{{"name", d->objectName()}, {"width", d->width()}, {"height", d->height()}});
            }
            QJsonArray header;
            for (QAction *a : m_header->actions()) {
                auto b = qobject_cast<QToolButton *>(m_header->widgetForAction(a));
                if (a->isVisible() && b)
                    header.append(QJsonObject{{"name", b->objectName()}, {"text", b->text()},
                                              {"words", b->toolButtonStyle() != Qt::ToolButtonIconOnly}});
            }
            const QRect frame = m_window->frameGeometry();
            const QSize least = m_window->minimumSizeHint().expandedTo(m_window->minimumSize());
            const QJsonObject report{{"width", m_window->width()}, {"height", m_window->height()},
                {"frame", QJsonObject{{"x", frame.x()}, {"y", frame.y()}, {"width", frame.width()}, {"height", frame.height()}}},
                {"minimum", QJsonObject{{"width", least.width()}, {"height", least.height()}}},
                {"welcome", m_welcome && m_welcome->isVisible()}, {"timeline", m_window->timelineDock()->isVisible()},
                {"player_tabs", m_window->player()->findChild<QTabBar *>()->isVisible()},
                {"player_canvas", m_window->player()->findChild<QWidget *>(QStringLiteral("focusPreviewCanvas"))
                                      && m_window->player()->findChild<QWidget *>(QStringLiteral("focusPreviewCanvas"))->isVisible()},
                {"steps", m_nav && m_nav->isVisible()}, {"steps_handle", m_railHandle && m_railHandle->isVisible()},
                {"home_active", m_homeActive}, {"timeline_shown", m_timelineShown},
                {"nav_hidden", m_nav && m_nav->isHidden()},
                {"progress", m_welcome && m_welcome->findChild<QWidget *>(QStringLiteral("welcomeProgress"))->isVisible()},
                {"header_level", m_header->property("focusHeaderLevel").toInt()}, {"header", header},
                {"project_shown", m_projectAction && m_projectAction->isVisible()},
                {"devicePixelRatio", m_window->devicePixelRatioF()}, {"fields", fields}, {"docks", docks}};
            QFile file(Settings.appDataLocation() + QStringLiteral("/focus-geometry.json"));
            if (file.open(QIODevice::WriteOnly))
                file.write(QJsonDocument(report).toJson());
        });
        action(QStringLiteral("focusQaMediaSelectAction"), tr("Select first media"), [this]() {
            auto view = m_window->findChild<QListView *>(QStringLiteral("focusMediaView"));
            if (view && view->model()->rowCount()) {
                const auto index = view->model()->index(0, 0);
                view->setCurrentIndex(index);
                view->selectionModel()->select(index, QItemSelectionModel::ClearAndSelect | QItemSelectionModel::Rows);
            }
        });
        action(QStringLiteral("focusQaPreviewMediaAction"), tr("Preview selected media"), [this]() {
            if (auto view = m_window->findChild<QListView *>(QStringLiteral("focusMediaView")))
                QMetaObject::invokeMethod(view, "doubleClicked", Qt::DirectConnection, Q_ARG(QModelIndex, view->currentIndex()));
        });
        action(QStringLiteral("focusQaDetailsAction"), tr("Toggle clip details"), [this]() {
            if (auto details = m_window->findChild<QGroupBox *>(QStringLiteral("focusClipDetails")))
                details->setChecked(!details->isChecked());
        });
        for (bool edited : {false, true})
            action(edited ? QStringLiteral("studioQaTextEditAction") : QStringLiteral("studioQaTextDraftAction"), tr("Test text entry"), [this, edited]() {
                if (auto text = m_window->findChild<QPlainTextEdit *>(QStringLiteral("studioTextContent")))
                    text->setPlainText(edited ? QStringLiteral("A simpler way to create") : QStringLiteral("Welcome aboard"));
                if (auto duration = m_window->findChild<QDoubleSpinBox *>(QStringLiteral("studioTextDuration")))
                    duration->setValue(2);
            });
        action(QStringLiteral("studioQaCaptionDraftAction"), tr("Test caption entry"), [this]() {
            if (auto text = m_window->findChild<QTextEdit *>(QStringLiteral("studioCaptionContent")))
                text->setPlainText(QStringLiteral("Captions should be this easy."));
        });
        for (bool clear : {false, true})
            action(clear ? QStringLiteral("focusQaClearSearchAction") : QStringLiteral("focusQaSearchAction"), tr("Test media search"), [this, clear]() {
                if (auto field = m_window->findChild<QLineEdit *>(QStringLiteral("focusMediaSearch")))
                    field->setText(clear ? QString() : QStringLiteral("no-such-clip-focus-qa"));
            });
        action(QStringLiteral("focusQaWelcomeAction"), tr("Show the welcome screen"), [this]() {
            if (m_welcome) {
                m_welcome->show();
                welcomeShown(true);
            }
        });
        // UI Automation checks drive the engine's menus through the menu bar: show or hide it on request.
        action(QStringLiteral("focusQaMenuBarAction"), tr("Toggle the menu bar"), [this]() {
            if (m_menuBar)
                m_menuBar->setVisible(!m_menuBar->isVisible());
        });
    }

    void saveLayout()
    {
        // folded away for the welcome screen only: the layout keeps it
        if (m_timelineFolded) {
            m_timelineFolded = false;
            m_window->timelineDock()->show();
        }
        // with the timeline hidden, the layout to come back to is the one it had
        const QByteArray state = !m_timelineShown && !m_timelineLayout.isEmpty() ? m_timelineLayout
                                 : m_preview                                     ? m_previewLayout
                                                                                 : m_window->saveState(4);
        m_settings.setValue(QStringLiteral("layout-v4"), state);
        m_settings.setValue(QStringLiteral("category"), m_category);
        m_settings.setValue(QStringLiteral("timeline-shown"), m_timelineShown);
        m_settings.sync();
    }

    // AI-live editing: the timeline off. The player and the AI chat get the room, and marking up the video full
    // screen (Review) is the way to give notes. Timeline on brings back the layout exactly as it was.
    void installLiveMode()
    {
        if (auto view = m_window->findChild<QMenu *>(QStringLiteral("menuView"))) {
            view->addSeparator();
            view->addAction(m_timelineAction);
        }
        auto layout = qobject_cast<QBoxLayout *>(m_window->player()->layout());
        if (!layout)
            return;
        using namespace LetItEditColors;
        m_liveBar = new QWidget(m_window->player());
        m_liveBar->setObjectName(QStringLiteral("focusLiveBar"));
        m_liveBar->setAttribute(Qt::WA_StyledBackground, true);
        m_liveBar->setStyleSheet(QStringLiteral(
                                     "QWidget#focusLiveBar { background: %1; border: 1px solid %2; border-radius: 12px; }"
                                     "QPushButton#focusLiveMarkUp { font-size: 17px; font-weight: 700; padding: 10px 26px; "
                                     "min-height: 26px; }"
                                     "QLabel#focusLiveHint { color: %3; font-size: 13px; }")
                                     .arg(panel, line, muted));
        auto row = new QHBoxLayout(m_liveBar);
        row->setContentsMargins(14, 10, 14, 10);
        row->setSpacing(10);
        auto markUp = new QPushButton(focusWorkspaceIcon(QStringLiteral("review")), tr("Review"), m_liveBar);
        markUp->setObjectName(QStringLiteral("focusLiveMarkUp"));
        markUp->setProperty("studioPrimary", true);
        markUp->setIconSize(QSize(22, 22));
        markUp->setToolTip(tr("Watch full screen, draw on the video and say what should change; your AI re-edits "
                              "(Ctrl+Shift+R)"));
        connect(markUp, &QPushButton::clicked, this, []() {
            if (auto review = Actions["reviewModeAction"])
                review->trigger();
        });
        row->addWidget(markUp);
        auto hint = new QLabel(tr("Talk to your AI on the right, or press Review to draw on the video and say what "
                                  "to change. Every change is one Undo step."),
                               m_liveBar);
        hint->setObjectName(QStringLiteral("focusLiveHint"));
        hint->setWordWrap(true);
        row->addWidget(hint, 1);
        auto hook = new QPushButton(focusWorkspaceIcon(QStringLiteral("hook")), tr("New hook"), m_liveBar);
        hook->setObjectName(QStringLiteral("focusLiveHook"));
        hook->setToolTip(tr("Try other openings for this video"));
        connect(hook, &QPushButton::clicked, this, []() {
            if (auto a = Actions["hookPanelAction"])
                a->trigger();
        });
        row->addWidget(hook);
        auto play = new QPushButton(tr("Play from the start"), m_liveBar);
        play->setObjectName(QStringLiteral("focusLivePlay"));
        connect(play, &QPushButton::clicked, this, [this]() {
            m_window->seekTimeline(0);
            m_window->player()->play();
        });
        row->addWidget(play);
        auto show = new QPushButton(focusWorkspaceIcon(QStringLiteral("timeline")), tr("Show timeline"), m_liveBar);
        show->setObjectName(QStringLiteral("focusLiveTimeline"));
        connect(show, &QPushButton::clicked, this, [this]() { setTimelineShown(true); });
        row->addWidget(show);
        layout->addWidget(m_liveBar);
        m_liveBar->hide();
    }

    void syncTimelineAction()
    {
        if (m_timelineAction)
            m_timelineAction->setChecked(m_timelineShown);
        m_window->setProperty("focusTimeline", m_timelineShown);
    }

    void setTimelineShown(bool on)
    {
        if (m_homeActive && m_welcome && !m_welcome->isVisible())
            welcomeShown(false);
        if (on == m_timelineShown) {
            syncTimelineAction();
            return;
        }
        leavePreview();
        m_window->setUpdatesEnabled(false);
        if (!on) {
            // the layout to come back to has the timeline, even when the welcome screen had folded it away
            if (m_timelineFolded) {
                m_timelineFolded = false;
                m_window->timelineDock()->show();
            }
            m_timelineLayout = m_homeActive && !m_homeLayout.isEmpty() ? m_homeLayout : m_window->saveState(4);
            m_timelineShown = false;
            auto chat = dock("aiChatDock");
            auto hook = dock("focusHookDock");
            const bool hookShown = hook && hook->isVisible();
            for (auto d : m_window->findChildren<QDockWidget *>())
                if (d != chat && d != hook)
                    d->hide();
            m_suppressedLeft.clear();
            if (m_nav)
                m_nav->hide();
            if (m_railHandle && !m_homeActive)
                m_railHandle->show();
            if (chat) {
                if (chat->isFloating() || m_window->dockWidgetArea(chat) != Qt::RightDockWidgetArea)
                    m_window->addDockWidget(Qt::RightDockWidgetArea, chat);
                chat->show();
                chat->raise();
                m_window->resizeDocks({chat}, {qBound(380, int(m_window->width() * 0.36), 620)}, Qt::Horizontal);
            }
            if (hookShown && chat)
                m_window->splitDockWidget(hook, chat, Qt::Vertical);
            if (m_liveBar)
                m_liveBar->show();
            m_window->statusBar()->showMessage(tr("Timeline hidden: talk to your AI, or press Review"), 4000);
        } else {
            m_timelineShown = true;
            if (m_liveBar)
                m_liveBar->hide();
            if (m_timelineLayout.isEmpty() || !m_window->restoreState(m_timelineLayout, 4)) {
                m_window->setUpdatesEnabled(true);
                resetLayout();
            }
            if (m_railHandle)
                m_railHandle->setVisible(m_railCollapsed);
            if (m_nav) {
                m_window->addToolBar(Qt::LeftToolBarArea, m_nav);
                m_nav->setVisible(!m_railCollapsed);
            }
            m_timelineLayout.clear();
            syncNavigation();
            welcomeShown(m_welcome && m_welcome->isVisible()); // nothing open yet: it folds away again
        }
        m_window->setUpdatesEnabled(true);
        syncTimelineAction();
        m_settings.setValue(QStringLiteral("timeline-shown"), m_timelineShown);
        if (m_homeActive) {
            for (auto *dockWidget : m_window->findChildren<QDockWidget *>())
                dockWidget->hide();
            if (m_nav)
                m_nav->hide();
            if (m_railHandle)
                m_railHandle->hide();
            if (m_liveBar)
                m_liveBar->hide();
        } else if (on && !m_railCollapsed) {
            // Qt can hide a toolbar while restoreState rearranges the left toolbar area.
            QTimer::singleShot(0, this, [this]() {
                if (m_timelineShown && !m_homeActive && !m_railCollapsed)
                    m_window->addToolBar(Qt::LeftToolBarArea, m_nav);
                if (m_timelineShown && !m_homeActive && !m_railCollapsed)
                    m_nav->show();
            });
        }
        QTimer::singleShot(0, this, [this]() { updateResponsiveLayout(); });
    }

    MainWindow *m_window;
    QSettings m_settings;
    QToolBar *m_nav{nullptr};
    QToolBar *m_railHandle{nullptr};
    QToolButton *m_exitFullScreen{nullptr};
    QAction *m_exitFullScreenAction{nullptr};
    bool m_railCollapsed{false};
    bool m_homeActive{false};
    QList<QPointer<QWidget>> m_homePlayerWidgets;
    QList<QPointer<QAction>> m_homeHeaderActions;
    QToolBar *m_header{nullptr};
    QPointer<QMenuBar> m_menuBar;
    QWidget *m_headerRight{nullptr};
    QAction *m_projectAction{nullptr};
    QAction *m_savedAction{nullptr};
    QToolButton *m_exportButton{nullptr};
    QLabel *m_project{nullptr};
    QLabel *m_saved{nullptr};
    QMap<QString, QAction *> m_categories;
    QAction *m_railAi{nullptr};
    QList<QToolButton *> m_responsiveButtons;
    QPointer<QDockWidget> m_suppressedLeft;
    QPointer<NewProjectFolder> m_engineStart;
    QPointer<WelcomePage> m_welcome;
    bool m_swapping{false};
    bool m_resizing{false};
    QString m_category{QStringLiteral("media")};
    QByteArray m_previewLayout;
    bool m_preview{false};
    QAction *m_timelineAction{nullptr};
    QWidget *m_liveBar{nullptr};
    bool m_timelineFolded{false}; // the timeline folded away while the welcome screen shows
    QWidget *m_headerSpring{nullptr};
    QToolButton *m_menuButton{nullptr};
    QList<QToolButton *> m_primaryButtons;   // New video, Review, Export: their words go last
    QList<QToolButton *> m_secondaryButtons; // Timeline, Ask the AI
    int m_projectWidth{320};
    bool m_fitting{false};
    QByteArray m_timelineLayout; // the layout to come back to when the timeline shows again
    QByteArray m_homeLayout; // the normal layout before the empty home concealed its panels
    bool m_timelineShown{true};
};

void installFocusWorkspace(MainWindow *window)
{
    if (focusWorkspaceEnabled())
        new FocusWorkspace(window);
}

