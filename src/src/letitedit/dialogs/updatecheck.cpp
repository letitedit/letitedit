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

#include "letitedit/dialogs/updatecheck.h"

#include "Logger.h"
#include "letitedit/dialogs/problemreport.h"
#include "mainwindow.h"
#include "settings.h"
#include "util.h"

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QRegularExpression>
#include <QtWidgets>

namespace UpdateCheck {

// The file naming the newest build (T368; on letitedit.app since 24 Nov 2026, the owner's yes). Only the person's own
// window (instance "main") reads it; test windows check nothing unless LETITEDIT_UPDATE_URL names a stand-in.
static const char kUpdateUrl[] = "https://letitedit.app/latest.json";
static const char kDownloadPage[] = "https://letitedit.app/";
static constexpr qint64 kDayMs = 24LL * 3600 * 1000;

static QPointer<QAction> g_checkAction;
static QPointer<QAction> g_automaticAction;
static QString g_readyUrl;

static QString settingsFile()
{
    return QDir::fromNativeSeparators(Settings.appDataLocation()) + QStringLiteral("/update-check.json");
}

static QJsonObject readSettings()
{
    QFile file(settingsFile());
    if (!file.open(QIODevice::ReadOnly))
        return QJsonObject();
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data = data.mid(3);
    return QJsonDocument::fromJson(data).object();
}

static void saveSettings(const QJsonObject &changes)
{
    QJsonObject values = readSettings();
    for (auto it = changes.begin(); it != changes.end(); ++it)
        values.insert(it.key(), it.value());
    QSaveFile file(settingsFile());
    if (file.open(QIODevice::WriteOnly)) {
        file.write(QJsonDocument(values).toJson());
        file.commit();
    }
}

static bool automatic()
{
    return readSettings().value(QStringLiteral("automatic")).toBool(true);
}

QString updateUrl()
{
    QString address;
    if (qEnvironmentVariableIsSet("LETITEDIT_UPDATE_URL"))
        address = qEnvironmentVariable("LETITEDIT_UPDATE_URL").trimmed();
    else if (qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main")) == QLatin1String("main"))
        address = QString::fromLatin1(kUpdateUrl);
    const QUrl url(address);
    if (address.compare(QStringLiteral("off"), Qt::CaseInsensitive) == 0 || !url.isValid() || !url.userInfo().isEmpty())
        return QString();
    if (url.scheme() == QLatin1String("https") && !url.host().isEmpty())
        return address;
    // the local stand-in of the checks
    if (url.scheme() == QLatin1String("http")
        && (url.host() == QLatin1String("127.0.0.1") || url.host() == QLatin1String("localhost")))
        return address;
    return QString();
}

static bool parseBuild(const QString &name, qint64 *day, int *number)
{
    static const QRegularExpression build(QStringLiteral("^(\\d{8})\\.(\\d+)$"));
    const auto m = build.match(name.trimmed());
    if (!m.hasMatch())
        return false;
    *day = m.captured(1).toLongLong();
    *number = m.captured(2).toInt();
    return true;
}

bool isNewer(const QString &latest, const QString &mine)
{
    qint64 latestDay = 0, mineDay = 0;
    int latestNumber = 0, mineNumber = 0;
    if (!parseBuild(latest, &latestDay, &latestNumber) || !parseBuild(mine, &mineDay, &mineNumber))
        return false;
    return latestDay > mineDay || (latestDay == mineDay && latestNumber > mineNumber);
}

static void showReady(const QJsonObject &latest)
{
    const QString candidate = latest.value(QStringLiteral("url")).toString();
    g_readyUrl = Util::isHttpsOnHost(candidate, QStringLiteral("letitedit.app")) ? candidate : QString::fromLatin1(kDownloadPage);
    const QString version = latest.value(QStringLiteral("version")).toString(latest.value(QStringLiteral("build")).toString())
                                .left(40);
    auto action = new QAction(QObject::tr("A new version of letitedit is ready (%1). Click here to get it.").arg(version), &MAIN);
    action->setObjectName(QStringLiteral("updateReadyAction"));
    QObject::connect(action, &QAction::triggered, &MAIN, []() { Util::openUrl(QUrl(g_readyUrl)); });
    MAIN.showStatusMessage(action, 30);
    if (g_checkAction)
        g_checkAction->setText(QObject::tr("A new version is ready (%1)...").arg(version));
}

// quiet: the daily check (says nothing unless a new version is ready)
static void checkNow(bool quiet)
{
    const QString address = updateUrl();
    if (address.isEmpty()) {
        if (!quiet)
            MAIN.showStatusMessage(QObject::tr("This version of letitedit can't check for updates yet."));
        return;
    }
    saveSettings({{QStringLiteral("last_check"), QDateTime::currentDateTimeUtc().toString(Qt::ISODate)}});
    QNetworkRequest request{QUrl(address)};
    request.setHeader(QNetworkRequest::UserAgentHeader, QStringLiteral("letitedit/%1").arg(ProblemReport::buildName()));
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
    request.setAttribute(QNetworkRequest::CookieLoadControlAttribute, QNetworkRequest::Manual);
    request.setAttribute(QNetworkRequest::CookieSaveControlAttribute, QNetworkRequest::Manual);
    request.setTransferTimeout(15000);
    auto network = new QNetworkAccessManager(&MAIN);
    QNetworkReply *reply = network->get(request);
    QObject::connect(reply, &QNetworkReply::finished, &MAIN, [reply, network, quiet]() {
        reply->deleteLater();
        network->deleteLater();
        const QJsonObject latest = reply->error() == QNetworkReply::NoError
                                       ? QJsonDocument::fromJson(reply->read(64 * 1024)).object()
                                       : QJsonObject();
        const QString build = latest.value(QStringLiteral("build")).toString();
        if (build.isEmpty()) {
            LOG_WARNING() << "update check: no answer" << reply->error();
            if (!quiet)
                MAIN.showStatusMessage(QObject::tr("Couldn't check for updates just now. Try again later."));
            return;
        }
        saveSettings({{QStringLiteral("latest"), latest}});
        if (isNewer(build, ProblemReport::buildName())) {
            LOG_INFO() << "update check: a newer build is ready" << build.left(20);
            showReady(latest);
        } else if (!quiet) {
            MAIN.showStatusMessage(QObject::tr("You have the newest letitedit."));
        }
    });
}

void addMenuItems(QWidget *window, QMenu *help)
{
    auto check = new QAction(QObject::tr("Check for updates"), window);
    check->setObjectName(QStringLiteral("actionCheckUpdates"));
    QObject::connect(check, &QAction::triggered, window, []() {
        if (!g_readyUrl.isEmpty())
            Util::openUrl(QUrl(g_readyUrl));
        else
            checkNow(false);
    });
    help->addAction(check);
    g_checkAction = check;
    auto daily = new QAction(QObject::tr("Check for updates automatically"), window);
    daily->setObjectName(QStringLiteral("actionCheckUpdatesAutomatically"));
    daily->setCheckable(true);
    daily->setChecked(automatic());
    daily->setToolTip(QObject::tr("Once a day, letitedit looks up whether a newer version is ready and says so. It never "
                                  "downloads or installs anything by itself."));
    QObject::connect(daily, &QAction::toggled, window, [](bool on) { saveSettings({{QStringLiteral("automatic"), on}}); });
    help->addAction(daily);
    g_automaticAction = daily;
}

static void checkIfDue()
{
    if (!automatic() || updateUrl().isEmpty())
        return;
    const QDateTime last = QDateTime::fromString(readSettings().value(QStringLiteral("last_check")).toString(), Qt::ISODate);
    if (last.isValid() && last.msecsTo(QDateTime::currentDateTimeUtc()) < kDayMs && last <= QDateTime::currentDateTimeUtc())
        return;
    checkNow(true);
}

void startDaily(QWidget *window)
{
    int delay = 30000;
    if (qEnvironmentVariableIsSet("LETITEDIT_QA") && qEnvironmentVariableIsSet("LETITEDIT_QA_UPDATE_DELAY_MS"))
        delay = qEnvironmentVariableIntValue("LETITEDIT_QA_UPDATE_DELAY_MS");
    QTimer::singleShot(delay, window, []() { checkIfDue(); });
    auto hourly = new QTimer(window);
    hourly->setInterval(3600 * 1000);
    QObject::connect(hourly, &QTimer::timeout, window, []() { checkIfDue(); });
    hourly->start();
}

} // namespace UpdateCheck
