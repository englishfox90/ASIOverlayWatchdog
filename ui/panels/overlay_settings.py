"""
Overlay Settings Panel
Text/Image overlay configuration with list, preview, and editor
Matches the old Tkinter UI layout and features
"""
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QAbstractItemView, QTableWidgetItem,
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, SubtitleLabel,
    PushButton, PrimaryPushButton,
    TableWidget,
)

from ..theme.tokens import Colors, Spacing, Layout
from ..theme.icons import mdi

from .overlay_preview import OverlayPreviewCard, TOKENS
from .overlay_editor_ui import OverlayEditorUIMixin


class OverlaySettingsPanel(OverlayEditorUIMixin, QWidget):
    """
    Overlay settings panel with 2-column layout:
    - Left: Overlay list + Preview
    - Right: Editor (text or image based on type)
    """

    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._overlays = []
        self._selected_index = -1
        self._setup_ui()

    def _setup_ui(self):
        self.setObjectName("overlaySettingsPanel")
        self.setStyleSheet(f"#overlaySettingsPanel {{ background-color: {Colors.bg_app}; }}")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        main_layout.setSpacing(Spacing.card_gap)

        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(Spacing.card_gap)

        list_card = self._create_list_card()
        left_layout.addWidget(list_card, stretch=1)

        self._preview = OverlayPreviewCard()
        left_layout.addWidget(self._preview, stretch=1)

        main_layout.addWidget(left_column, stretch=2)

        editor_card = self._create_editor_card()
        main_layout.addWidget(editor_card, stretch=3)

    def _create_list_card(self) -> CardWidget:
        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                  Spacing.card_padding, Spacing.card_padding)
        layout.setSpacing(Spacing.md)

        header = SubtitleLabel("Overlay List")
        header.setStyleSheet(f"color: {Colors.text_primary};")
        layout.addWidget(header)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.md)

        self.add_btn = PrimaryPushButton("Add")
        self.add_btn.setIcon(mdi('plus'))
        self.add_btn.setFixedWidth(90)
        self.add_btn.clicked.connect(self._show_add_menu)
        btn_row.addWidget(self.add_btn)

        self.dup_btn = PushButton("Duplicate")
        self.dup_btn.setIcon(mdi('content-copy'))
        self.dup_btn.setFixedWidth(115)
        self.dup_btn.clicked.connect(self._duplicate_overlay)
        btn_row.addWidget(self.dup_btn)

        self.del_btn = PushButton("Delete")
        self.del_btn.setIcon(mdi('delete-outline'))
        self.del_btn.setFixedWidth(90)
        self.del_btn.clicked.connect(self._delete_overlay)
        btn_row.addWidget(self.del_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.overlay_table = TableWidget()
        self.overlay_table.setColumnCount(3)
        self.overlay_table.setHorizontalHeaderLabels(["Name", "Type", "Summary"])
        self.overlay_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.overlay_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.overlay_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.overlay_table.verticalHeader().setVisible(False)
        self.overlay_table.itemSelectionChanged.connect(self._on_overlay_selected)

        header = self.overlay_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.resizeSection(0, 120)
        header.resizeSection(1, 60)

        self.overlay_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {Colors.bg_input};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
                gridline-color: {Colors.border_subtle};
            }}
            QTableWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid {Colors.border_subtle};
            }}
            QTableWidget::item:selected {{
                background-color: {Colors.accent_default};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {Colors.gray_8};
                color: {Colors.text_secondary};
                padding: 8px;
                border: none;
                border-bottom: 2px solid {Colors.border_subtle};
                font-weight: bold;
            }}
        """)

        layout.addWidget(self.overlay_table)

        return card

    def _update_preview(self):
        current = None
        if 0 <= self._selected_index < len(self._overlays):
            current = self._overlays[self._selected_index]
        self._preview.set_overlay(current)

    # === LIST OPERATIONS ===

    def _refresh_list(self):
        saved_index = self._selected_index
        self.overlay_table.blockSignals(True)

        self.overlay_table.setRowCount(0)
        for i, overlay in enumerate(self._overlays):
            self.overlay_table.insertRow(i)

            name = overlay.get('name', 'Unnamed')
            otype = overlay.get('type', 'text').capitalize()

            if otype == 'Image':
                path = overlay.get('image_path', '')
                summary = os.path.basename(path) if path else overlay.get('anchor', 'Bottom-Right')
            else:
                text = overlay.get('text', '')
                summary = text[:35].replace('\n', ' ')
                if len(text) > 35:
                    summary += '...'
                if not summary:
                    summary = overlay.get('anchor', 'Bottom-Left')

            self.overlay_table.setItem(i, 0, QTableWidgetItem(name))
            self.overlay_table.setItem(i, 1, QTableWidgetItem(otype))
            self.overlay_table.setItem(i, 2, QTableWidgetItem(summary))

        if 0 <= saved_index < len(self._overlays):
            self.overlay_table.selectRow(saved_index)

        self.overlay_table.blockSignals(False)

    def _update_list_row(self, index: int):
        """Update only the display cells for one row without rebuilding the table."""
        if index < 0 or index >= len(self._overlays) or index >= self.overlay_table.rowCount():
            return
        overlay = self._overlays[index]
        name = overlay.get('name', 'Unnamed')
        otype = overlay.get('type', 'text').capitalize()
        if otype == 'Image':
            path = overlay.get('image_path', '')
            summary = os.path.basename(path) if path else overlay.get('anchor', 'Bottom-Right')
        else:
            text = overlay.get('text', '')
            summary = text[:35].replace('\n', ' ')
            if len(text) > 35:
                summary += '...'
            if not summary:
                summary = overlay.get('anchor', 'Bottom-Left')
        if self.overlay_table.item(index, 0):
            self.overlay_table.item(index, 0).setText(name)
            self.overlay_table.item(index, 1).setText(otype)
            self.overlay_table.item(index, 2).setText(summary)

    def _show_add_menu(self):
        from qfluentwidgets import RoundMenu, Action
        menu = RoundMenu(parent=self)
        menu.addAction(Action(mdi('format-text'), "Add Text Overlay", triggered=self._add_text_overlay))
        menu.addAction(Action(mdi('image-outline'), "Add Image Overlay", triggered=self._add_image_overlay))
        menu.addAction(Action(mdi('compass-outline'), "Add Compass Rose", triggered=self._add_compass_overlay))

        pos = self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft())
        menu.exec(pos)

    def _add_text_overlay(self):
        new_overlay = {
            'name': f'Text {len(self._overlays) + 1}',
            'type': 'text',
            'text': '{CAMERA}\n{EXPOSURE}',
            'anchor': 'Bottom-Left',
            'offset_x': 15,
            'offset_y': 15,
            'font_size': 24,
            'font_style': 'normal',
            'color': 'white',
            'alignment': 'left',
            'bg_enabled': False,
            'bg_color': 'transparent'
        }
        self._overlays.append(new_overlay)
        self._refresh_list()
        self.overlay_table.blockSignals(False)
        self.overlay_table.selectRow(len(self._overlays) - 1)
        self._save_overlays()

    def _add_image_overlay(self):
        new_overlay = {
            'name': f'Image {len(self._overlays) + 1}',
            'type': 'image',
            'image_path': '',
            'anchor': 'Bottom-Right',
            'offset_x': 15,
            'offset_y': 15,
            'width': 100,
            'height': 100,
            'opacity': 100,
            'maintain_aspect': True
        }
        self._overlays.append(new_overlay)
        self._refresh_list()
        self.overlay_table.selectRow(len(self._overlays) - 1)
        self._save_overlays()

    def _add_compass_overlay(self):
        new_overlay = {
            'name': 'Compass Rose',
            'type': 'compass',
            'rotation': 0,
            'size': 80,
            'mirror': False,
            'anchor': 'Bottom-Right',
            'offset_x': 20,
            'offset_y': 20,
        }
        self._overlays.append(new_overlay)
        self._refresh_list()
        self.overlay_table.selectRow(len(self._overlays) - 1)
        self._save_overlays()

    def _duplicate_overlay(self):
        if 0 <= self._selected_index < len(self._overlays):
            original = self._overlays[self._selected_index]
            duplicate = original.copy()
            duplicate['name'] = f"{original.get('name', 'Overlay')} Copy"
            self._overlays.append(duplicate)
            self._refresh_list()
            self.overlay_table.selectRow(len(self._overlays) - 1)
            self._save_overlays()

    def _delete_overlay(self):
        if 0 <= self._selected_index < len(self._overlays):
            del self._overlays[self._selected_index]
            self._refresh_list()
            self._selected_index = -1
            self._clear_editor()
            self._save_overlays()
            self._update_preview()

    def _on_overlay_selected(self):
        rows = self.overlay_table.selectedIndexes()
        if rows:
            self._selected_index = rows[0].row()
            if 0 <= self._selected_index < len(self._overlays):
                self._load_overlay_to_editor(self._overlays[self._selected_index])
                self._update_preview()
        else:
            self._selected_index = -1
            self._clear_editor()
            self._update_preview()

    # === EDITOR OPERATIONS ===

    def _load_overlay_to_editor(self, overlay: dict):
        self._block_all_signals(True)

        self.name_edit.setText(overlay.get('name', ''))

        overlay_type = overlay.get('type', 'text')
        type_map = {'text': 0, 'image': 1, 'compass': 2}
        type_idx = type_map.get(overlay_type, 0)
        self.type_combo.setCurrentIndex(type_idx)
        self.editor_stack.setCurrentIndex(type_idx)

        if overlay_type == 'text':
            self.text_edit.setPlainText(overlay.get('text', ''))
            self.font_size_spin.setValue(overlay.get('font_size', 24))

            color = overlay.get('color', 'white')
            idx = self.color_combo.findText(color)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)

            style = overlay.get('font_style', 'normal')
            idx = self.font_style_combo.findText(style)
            if idx >= 0:
                self.font_style_combo.setCurrentIndex(idx)

            alignment = overlay.get('alignment', 'left')
            idx = self.text_align_combo.findText(alignment)
            if idx >= 0:
                self.text_align_combo.setCurrentIndex(idx)

            bg_enabled = overlay.get('bg_enabled', False)
            self.bg_switch.set_checked(bg_enabled)
            self.bg_color_widget.setVisible(bg_enabled)

            bg_color = overlay.get('bg_color', 'black')
            idx = self.bg_color_combo.findText(bg_color)
            if idx >= 0:
                self.bg_color_combo.setCurrentIndex(idx)
        elif overlay_type == 'image':
            self.image_path_edit.setText(overlay.get('image_path', ''))
            self.image_width_spin.setValue(overlay.get('width', 100))
            self.image_height_spin.setValue(overlay.get('height', 100))
            self.opacity_spin.setValue(overlay.get('opacity', 100))
            self.aspect_switch.set_checked(overlay.get('maintain_aspect', True))
        elif overlay_type == 'compass':
            self.compass_rotation_spin.setValue(overlay.get('rotation', 0))
            self.compass_size_spin.setValue(overlay.get('size', 80))
            self.compass_mirror_switch.set_checked(overlay.get('mirror', False))

        anchor = overlay.get('anchor', 'Bottom-Left')
        idx = self.anchor_combo.findText(anchor)
        if idx >= 0:
            self.anchor_combo.setCurrentIndex(idx)

        self.offset_x_spin.setValue(overlay.get('offset_x', 15))
        self.offset_y_spin.setValue(overlay.get('offset_y', 15))

        self._block_all_signals(False)

    def _block_all_signals(self, block: bool):
        widgets = [
            self.name_edit, self.type_combo, self.text_edit,
            self.font_size_spin, self.color_combo, self.font_style_combo,
            self.text_align_combo, self.bg_color_combo,
            self.image_path_edit, self.image_width_spin, self.image_height_spin,
            self.opacity_spin,
            self.compass_rotation_spin, self.compass_size_spin,
            self.anchor_combo, self.offset_x_spin, self.offset_y_spin
        ]
        for w in widgets:
            w.blockSignals(block)
        self.bg_switch.switch.blockSignals(block)
        self.aspect_switch.switch.blockSignals(block)
        self.compass_mirror_switch.switch.blockSignals(block)

    def _clear_editor(self):
        self._block_all_signals(True)
        self.name_edit.clear()
        self.type_combo.setCurrentIndex(0)
        self.editor_stack.setCurrentIndex(0)
        self.text_edit.clear()
        self.font_size_spin.setValue(24)
        self.color_combo.setCurrentIndex(0)
        self.font_style_combo.setCurrentIndex(0)
        self.bg_switch.set_checked(False)
        self.bg_color_widget.hide()
        self.image_path_edit.clear()
        self.image_width_spin.setValue(100)
        self.image_height_spin.setValue(100)
        self.opacity_spin.setValue(100)
        self.aspect_switch.set_checked(True)
        self.compass_mirror_switch.set_checked(False)
        self.anchor_combo.setCurrentIndex(0)
        self.offset_x_spin.setValue(15)
        self.offset_y_spin.setValue(15)
        self._block_all_signals(False)

    def _update_current_overlay(self):
        if 0 <= self._selected_index < len(self._overlays):
            overlay = self._overlays[self._selected_index]
            overlay['name'] = self.name_edit.text()
            type_map = {0: 'text', 1: 'image', 2: 'compass'}
            overlay['type'] = type_map.get(self.type_combo.currentIndex(), 'text')

            if overlay['type'] == 'text':
                overlay['text'] = self.text_edit.toPlainText()
                overlay['font_size'] = self.font_size_spin.value()
                overlay['color'] = self.color_combo.currentText()
                overlay['font_style'] = self.font_style_combo.currentText()
                overlay['alignment'] = self.text_align_combo.currentText()
                overlay['bg_enabled'] = self.bg_switch.is_checked()
                overlay['bg_color'] = self.bg_color_combo.currentText()
            elif overlay['type'] == 'image':
                overlay['image_path'] = self.image_path_edit.text()
                overlay['width'] = self.image_width_spin.value()
                overlay['height'] = self.image_height_spin.value()
                overlay['opacity'] = self.opacity_spin.value()
                overlay['maintain_aspect'] = self.aspect_switch.is_checked()
            elif overlay['type'] == 'compass':
                overlay['rotation'] = self.compass_rotation_spin.value()
                overlay['size'] = self.compass_size_spin.value()
                overlay['mirror'] = self.compass_mirror_switch.is_checked()

            overlay['anchor'] = self.anchor_combo.currentText()
            overlay['offset_x'] = self.offset_x_spin.value()
            overlay['offset_y'] = self.offset_y_spin.value()

    def _insert_token(self):
        selected_label = self.token_combo.currentText()
        if selected_label.startswith("──"):
            return
        for label, token in TOKENS:
            if label == selected_label and token is not None:
                self.text_edit.insertPlainText(token)
                break

    def _browse_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Overlay Image",
            "",
            "Images (*.png *.jpg *.jpeg *.gif *.bmp);;All Files (*)"
        )
        if file_path:
            self.image_path_edit.setText(file_path)
            self._preview.clear_image_cache(file_path)
            self._on_image_changed()

    # === EVENT HANDLERS ===

    def _on_type_changed(self, text):
        type_map = {"Text": 0, "Image": 1, "Compass": 2}
        self.editor_stack.setCurrentIndex(type_map.get(text, 0))
        self._update_current_overlay()
        self._update_list_row(self._selected_index)
        self._update_preview()

    def _on_name_changed(self, text):
        self._update_current_overlay()
        self._update_list_row(self._selected_index)

    def _on_text_changed(self):
        if self._selected_index >= 0:
            self._update_current_overlay()
            self._update_list_row(self._selected_index)
            self._update_preview()

    def _on_appearance_changed(self):
        self._update_current_overlay()
        self._update_preview()

    def _on_position_changed(self):
        self._update_current_overlay()
        self._update_preview()

    def _on_bg_toggle(self, state):
        self.bg_color_widget.setVisible(bool(state))
        self._update_current_overlay()
        self._update_preview()

    def _on_compass_field_changed(self):
        self._update_current_overlay()
        self._update_list_row(self._selected_index)
        self._update_preview()

    def _on_image_changed(self):
        self._update_current_overlay()
        self._update_list_row(self._selected_index)
        self._update_preview()

    def _on_image_size_changed(self):
        if self.aspect_switch.is_checked():
            image_path = self.image_path_edit.text()
            if image_path and os.path.exists(image_path):
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    aspect = pixmap.height() / pixmap.width() if pixmap.width() > 0 else 1
                    sender = self.sender()
                    if sender == self.image_width_spin:
                        self.image_height_spin.blockSignals(True)
                        self.image_height_spin.setValue(int(self.image_width_spin.value() * aspect))
                        self.image_height_spin.blockSignals(False)
                    elif sender == self.image_height_spin:
                        self.image_width_spin.blockSignals(True)
                        self.image_width_spin.setValue(int(self.image_height_spin.value() / aspect))
                        self.image_width_spin.blockSignals(False)

        self._update_current_overlay()
        self._update_preview()

    def _on_aspect_toggle(self, state):
        self._on_image_size_changed()

    def _apply_changes(self):
        self._update_current_overlay()
        self._save_overlays()

    def _reset_editor(self):
        if 0 <= self._selected_index < len(self._overlays):
            self._load_overlay_to_editor(self._overlays[self._selected_index])

    def _save_overlays(self):
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('overlays', self._overlays)
            self.settings_changed.emit()

    # === CONFIG LOADING ===

    def load_from_config(self, config):
        self._overlays = config.get('overlays', [])
        self._refresh_list()
        self._selected_index = -1
        self._clear_editor()
        self._update_preview()
        if hasattr(self, 'token_combo'):
            self._populate_token_combo()
