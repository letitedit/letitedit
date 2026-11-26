/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef FOCUSINSPECTOR_H
#define FOCUSINSPECTOR_H

#include "ui_avformatproducerwidget.h"
#include <QtWidgets>

inline void installFocusProducerInspector(QWidget *widget, Ui::AvformatProducerWidget *ui)
{
    if (!qApp->property("focusWorkspace").toBool())
        return;
    ui->filenameLabel->setPalette(qApp->palette());
    ui->filenameLabel->setStyleSheet(QStringLiteral("QLineEdit { background: palette(base); color: palette(text); border: none; border-bottom: 1px solid palette(mid); border-radius: 0; font-weight: 600; padding: 5px 0; }"));
    ui->filenameLabel->setAlignment(Qt::AlignLeft);
    ui->filenameLabel->setAccessibleName(QObject::tr("Clip name"));
    ui->verticalLayout->setContentsMargins(12, 10, 12, 12);
    ui->verticalLayout->setSpacing(12);
    // Let the Inspector's outer scroll area scroll the whole form, rather than
    // nesting two scroll areas above a permanently oversized utility button row.
    auto content = ui->scrollArea->takeWidget();
    ui->verticalLayout->removeWidget(ui->scrollArea);
    ui->scrollArea->hide();
    content->setParent(widget);
    ui->verticalLayout->insertWidget(1, content);
    ui->verticalLayout_2->setContentsMargins(0, 0, 0, 0);
    ui->verticalLayout_2->setSpacing(10);

    auto clearLayout = [](auto &&self, QLayout *layout) -> void {
        while (auto item = layout->takeAt(0)) {
            if (auto nested = item->layout())
                self(self, nested);
            delete item; // QWidgetItems never own the widgets or their signals.
        }
    };
    ui->verticalLayout_2->removeItem(ui->gridLayout_1);
    clearLayout(clearLayout, ui->gridLayout_1);
    delete ui->gridLayout_1;
    auto form = new QFormLayout;
    form->setRowWrapPolicy(QFormLayout::WrapLongRows);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    form->setLabelAlignment(Qt::AlignLeft | Qt::AlignVCenter);
    form->setSpacing(8);
    auto speed = new QHBoxLayout;
    speed->setSpacing(5);
    speed->addWidget(ui->speedSpinBox);
    ui->speedComboBox->setMinimumWidth(72);
    ui->speedComboBox->setMaximumWidth(84);
    speed->addWidget(ui->speedComboBox);
    speed->addWidget(ui->applySpeedButton);
    form->addRow(ui->speedLabel, speed);
    form->addRow(ui->pitchCheckBox);
    form->addRow(ui->durationLabel, ui->durationSpinBox);
    ui->durationLabel->setText(QObject::tr("Source length"));
    ui->timelineDurationLabel->setText(QObject::tr("Clip length"));
    form->addRow(ui->timelineDurationLabel, ui->timelineDurationText);
    ui->verticalLayout_2->insertLayout(0, form);

    // Stack labels above the native video/audio controls. No value, validation,
    // signal, object name or edit command changes when the form becomes narrow.
    for (auto grid : {ui->gridLayout_2, ui->gridLayout_3}) {
        struct Cell { QLayoutItem *item; int row, col, rows, cols; };
        QList<Cell> cells;
        while (grid->count()) {
            int r, c, rs, cs;
            grid->getItemPosition(0, &r, &c, &rs, &cs);
            cells.append({grid->takeAt(0), r, c, rs, cs});
        }
        for (const auto &cell : cells)
            grid->addItem(cell.item, cell.row * 2 + (cell.col > 0 ? 1 : 0), 0, 1, 3);
        grid->setHorizontalSpacing(0);
        grid->setVerticalSpacing(6);
    }
    ui->verticalLayout_2->removeWidget(ui->tabWidget);
    auto details = new QGroupBox(QObject::tr("Video / audio details"), content);
    details->setObjectName(QStringLiteral("focusClipDetails"));
    details->setCheckable(true);
    details->setChecked(false);
    auto detailsLayout = new QVBoxLayout(details);
    detailsLayout->setContentsMargins(4, 6, 4, 4);
    detailsLayout->addWidget(ui->tabWidget);
    ui->tabWidget->hide();
    QObject::connect(details, &QGroupBox::toggled, ui->tabWidget, &QWidget::setVisible);
    ui->verticalLayout_2->insertWidget(1, details);

    ui->verticalLayout->removeItem(ui->horizontalLayout_8);
    clearLayout(clearLayout, ui->horizontalLayout_8);
    delete ui->horizontalLayout_8;
    auto footer = new QHBoxLayout;
    auto operations = new QToolButton(widget);
    operations->setText(QObject::tr("Clip actions"));
    operations->setAccessibleName(QObject::tr("Convert, reverse, proxy and reload clip"));
    operations->setPopupMode(QToolButton::InstantPopup);
    auto menu = new QMenu(operations);
    QList<QPair<QAction *, QPushButton *>> entries;
    for (const char *name : {"convertButton", "reverseButton", "proxyButton", "openWithButton", "reloadButton"}) {
        auto b = widget->findChild<QPushButton *>(QString::fromLatin1(name));
        if (!b)
            continue;
        auto a = menu->addAction(b->text());
        QObject::connect(a, &QAction::triggered, b, &QPushButton::click);
        entries.append(qMakePair(a, b));
        b->hide();
    }
    QObject::connect(menu, &QMenu::aboutToShow, menu, [entries]() {
        for (const auto &entry : entries)
            entry.first->setEnabled(entry.second->isEnabled());
    });
    operations->setMenu(menu);
    footer->addWidget(operations);
    footer->addStretch();
    ui->menuButton->setText(QObject::tr("More…"));
    footer->addWidget(ui->menuButton);
    ui->verticalLayout->addLayout(footer);
    widget->setMinimumWidth(0);
    widget->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
}
#endif
