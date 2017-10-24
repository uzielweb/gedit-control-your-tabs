# -*- coding: utf-8 -*-
#
# __init__.py
# This file is part of Control Your Tabs, a plugin for gedit
#
# Copyright (C) 2010-2014, 2016-2017 Jeffery To <jeffery.to@gmail.com>
# https://github.com/jefferyto/gedit-control-your-tabs
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gedit', '3.0')

import math
import os.path
from functools import wraps
from gi.repository import GObject, GLib, Gtk, Gdk, GdkPixbuf, Gio, Gedit, PeasGtk
from .utils import connect_handlers, disconnect_handlers
from . import keyinfo, tabinfo, tabinfo_pre312

BASE_PATH = os.path.dirname(os.path.realpath(__file__))
LOCALE_PATH = os.path.join(BASE_PATH, 'locale')

try:
	import gettext
	gettext.bindtextdomain('gedit-control-your-tabs', LOCALE_PATH)
	_ = lambda s: gettext.dgettext('gedit-control-your-tabs', s)
except:
	_ = lambda s: s


class ControlYourTabsWindowActivatable(GObject.Object, Gedit.WindowActivatable):

	__gtype_name__ = 'ControlYourTabsWindowActivatable'

	window = GObject.property(type=Gedit.Window) # lowercase 'p' for gedit < 3.4

	MAX_TAB_WINDOW_ROWS = 9

	MAX_TAB_WINDOW_HEIGHT_PERCENTAGE = 0.5


	def __init__(self):
		GObject.Object.__init__(self)

	def do_activate(self):
		window = self.window
		tab_models = {}

		tabwin = Gtk.Window.new(Gtk.WindowType.POPUP)
		tabwin.set_transient_for(window)
		tabwin.set_destroy_with_parent(True)
		tabwin.set_accept_focus(False)
		tabwin.set_decorated(False)
		tabwin.set_resizable(False)
		tabwin.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
		tabwin.set_type_hint(Gdk.WindowTypeHint.UTILITY)
		tabwin.set_skip_taskbar_hint(False)
		tabwin.set_skip_pager_hint(False)

		sw = Gtk.ScrolledWindow.new(None, None)
		sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
		sw.show()

		tabwin.add(sw)

		view = Gtk.TreeView.new()
		view.set_enable_search(False)
		view.set_headers_visible(False)
		view.show()

		sw.add(view)

		col = Gtk.TreeViewColumn.new()
		col.set_title(_("Documents"))
		col.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)

		icon_cell = Gtk.CellRendererPixbuf.new()
		name_cell = Gtk.CellRendererText.new()
		space_cell = Gtk.CellRendererPixbuf.new()

		col.pack_start(icon_cell, False)
		col.pack_start(name_cell, True)
		col.pack_start(space_cell, False)

		col.add_attribute(icon_cell, 'pixbuf', 0)
		col.add_attribute(name_cell, 'markup', 1)

		view.append_column(col)

		sel = view.get_selection()
		sel.set_mode(Gtk.SelectionMode.SINGLE)

		# hack to ensure tabwin is correctly positioned/sized on first show
		view.realize()

		try:
			GtkStack = Gtk.Stack
		except AttributeError:
			is_side_panel_stack = False
		else:
			is_side_panel_stack = isinstance(window.get_side_panel(), GtkStack) # since 3.12

		self._is_switching = False
		self._is_tabwin_visible = False
		self._is_control_held = keyinfo.default_control_held()
		self._initial_tab = None
		self._multi = None
		self._tab_models = tab_models
		self._tabwin = tabwin
		self._view = view
		self._sw = sw
		self._icon_cell = icon_cell
		self._space_cell = space_cell
		self._tabwin_resize_id = None
		self._settings = get_settings()
		self._tabinfo = tabinfo if is_side_panel_stack else tabinfo_pre312

		tab = window.get_active_tab()

		if tab:
			self._setup(window, tab, tab_models)

			if self._multi:
				self.active_tab_changed(tab, tab_models[tab.get_parent()])

		else:
			connect_handlers(self, window, ['tab-added'], 'setup', tab_models)

	def do_deactivate(self):
		multi = self._multi
		tab_models = self._tab_models

		for notebook in list(tab_models.keys()):
			self.untrack_notebook(notebook, tab_models)

		if multi:
			disconnect_handlers(self, multi)

		disconnect_handlers(self, self.window)

		self.cancel_tabwin_resize()
		self.end_switching()

		self._tabwin.destroy()

		self._is_switching = None
		self._is_tabwin_visible = None
		self._is_control_held = None
		self._initial_tab = None
		self._multi = None
		self._tab_models = None
		self._tabwin = None
		self._view = None
		self._sw = None
		self._icon_cell = None
		self._space_cell = None
		self._tabwin_resize_id = None
		self._settings = None
		self._tabinfo = None

	def do_update_state(self):
		pass


	# plugin setup

	def on_setup_tab_added(self, window, tab, tab_models):
		disconnect_handlers(self, window)

		self._setup(window, tab, tab_models)

	def _setup(self, window, tab, tab_models):
		icon_size = self._tabinfo.get_tab_icon_size(tab)

		self._icon_cell.set_fixed_size(icon_size, icon_size)
		self._space_cell.set_fixed_size(icon_size, icon_size)

		multi = get_multi_notebook(tab)

		if not multi:
			try:
				Gedit.debug_plugin_message("cannot find multi notebook from %s", tab)
			except AttributeError: # gedit < 3.4
				pass

			return

		connect_handlers(
			self, multi,
			[
				'notebook-added',
				'notebook-removed',
				'tab-added',
				'tab-removed'
			],
			'multi_notebook',
			tab_models
		)
		connect_handlers(
			self, window,
			[
				'tabs-reordered',
				'active-tab-changed',
				'key-press-event',
				'key-release-event',
				'focus-out-event',
				'configure-event'
			],
			'window',
			tab_models
		)

		self._multi = multi

		for document in window.get_documents():
			notebook = Gedit.Tab.get_from_document(document).get_parent()
			self.track_notebook(notebook, tab_models)


	# tracking notebooks / tabs

	def track_notebook(self, notebook, tab_models):
		if notebook in tab_models:
			return

		tab_model = ControlYourTabsTabModel(self._tabinfo)

		connect_handlers(
			self, tab_model,
			[
				'row-inserted',
				'row-deleted',
				'row-changed'
			],
			self.on_tab_model_row_changed
		)
		connect_handlers(
			self, tab_model,
			[
				'selected-path-changed'
			],
			'tab_model'
		)

		tab_models[notebook] = tab_model

		for tab in notebook.get_children():
			self.track_tab(tab, tab_model)

	def untrack_notebook(self, notebook, tab_models):
		if notebook not in tab_models:
			return

		tab_model = tab_models[notebook]

		for tab in notebook.get_children():
			self.untrack_tab(tab, tab_model)

		if self.is_active_view_model(tab_model):
			self.set_active_view_model(None)

		disconnect_handlers(self, tab_model)

		del tab_models[notebook]

	def track_tab(self, tab, tab_model):
		if tab in tab_model:
			return

		tab_model.append(tab)

		connect_handlers(
			self, tab,
			[
				'notify::name',
				'notify::state'
			],
			self.on_tab_notify_name_state,
			tab_model
		)

	def untrack_tab(self, tab, tab_model):
		if tab == self._initial_tab:
			self._initial_tab = None

		if tab not in tab_model:
			return

		disconnect_handlers(self, tab)

		tab_model.remove(tab)

	def active_tab_changed(self, tab, tab_model):
		if not self._is_switching:
			if tab not in tab_model:
				# can this happen?
				self.track_tab(tab, tab_model)

			tab_model.move_after(tab)

		tab_model.select(tab)

		if not self.is_active_view_model(tab_model):
			self.set_active_view_model(tab_model)
			self.schedule_tabwin_resize()


	# signal handlers

	def on_multi_notebook_notebook_added(self, multi, notebook, tab_models):
		self.track_notebook(notebook, tab_models)

	def on_multi_notebook_notebook_removed(self, multi, notebook, tab_models):
		self.untrack_notebook(notebook, tab_models)

	def on_multi_notebook_tab_added(self, multi, notebook, tab, tab_models):
		self.track_tab(tab, tab_models[notebook])

	def on_multi_notebook_tab_removed(self, multi, notebook, tab, tab_models):
		self.untrack_tab(tab, tab_models[notebook])

	def on_window_tabs_reordered(self, window, tab_models):
		# XXX reordering tabs doesn't necessarily involve the active tab
		# and reordering only happens within a notebook, not across notebooks
		# ...
		multi = self._multi
		tab = window.get_active_tab()
		new_notebook = tab.get_parent()

		tab_model = tab_models[new_notebook]

		if tab in tab_model:
			return

		old_notebook = None

		for notebook in tab_models:
			tab_model = tab_models[notebook]
			if tab in tab_model:
				old_notebook = notebook
				break

		if old_notebook:
			self.untrack_tab(tab, tab_models[old_notebook])

		self.track_tab(tab, tab_models[new_notebook])

	def on_window_active_tab_changed(self, window, tab, tab_models):
		self.active_tab_changed(tab, tab_models[tab.get_parent()])

	def on_window_key_press_event(self, window, event, tab_models):
		self._is_control_held = keyinfo.updated_control_held(event, self._is_control_held, True)

		return self.key_press_event(event)

	def on_window_key_release_event(self, window, event, tab_models):
		self._is_control_held = keyinfo.updated_control_held(event, self._is_control_held, False)

		if not any(self._is_control_held):
			self.end_switching()

	def on_window_focus_out_event(self, window, event, tab_models):
		self.end_switching()

	def on_window_configure_event(self, window, event, tab_models):
		self.schedule_tabwin_resize()

	def on_tab_notify_name_state(self, tab, pspec, tab_model):
		if tab not in tab_model:
			return

		tab_model.update(tab)

	def on_tab_model_row_changed(self, tab_model, path):
		if not self.is_active_view_model(tab_model):
			return

		self.schedule_tabwin_resize()

	def on_tab_model_selected_path_changed(self, tab_model, path):
		if not self.is_active_view_model(tab_model):
			return

		self.set_view_selection(path)


	# tree view

	def is_active_view_model(self, tab_model):
		model = tab_model.model if tab_model else None
		return self._view.get_model() is model

	def set_active_view_model(self, tab_model):
		model = None
		selected_path = None

		if tab_model:
			model = tab_model.model
			selected_path = tab_model.get_selected_path()

		self._view.set_model(model)
		self.set_view_selection(selected_path)

	def set_view_selection(self, path):
		view = self._view
		selection = view.get_selection()

		if path:
			selection.select_path(path)
			view.scroll_to_cell(path, None, True, 0.5, 0)

		else:
			selection.unselect_all()


	# tab switching

	def key_press_event(self, event):
		settings = self._settings
		is_control_tab, is_control_page, is_control_escape = keyinfo.is_control_keys(event)
		block_event = True

		if is_control_tab and settings and settings['use-tabbar-order']:
			is_control_tab = False
			is_control_page = True

		if self._is_switching and is_control_escape:
			self.end_switching(True)

		elif is_control_tab or is_control_page:
			self.switch_tab(is_control_tab, keyinfo.is_next_key(event), event.time)

		else:
			block_event = self._is_switching

		return block_event

	def switch_tab(self, use_mru_order, to_next_tab, time):
		window = self.window
		current_tab = window.get_active_tab()

		if not current_tab:
			return

		notebook = current_tab.get_parent()

		tabs = self._tab_models[notebook] if use_mru_order else notebook.get_children()
		num_tabs = len(tabs)

		if num_tabs < 2 or current_tab not in tabs:
			return

		current_index = tabs.index(current_tab)
		step = 1 if to_next_tab else -1
		next_index = (current_index + step) % num_tabs

		next_tab = tabs[next_index]

		if not self._is_switching:
			self._initial_tab = current_tab

		self._is_switching = True

		window.set_active_tab(next_tab)

		if use_mru_order:
			tabwin = self._tabwin

			if not self._is_tabwin_visible:
				tabwin.show_all()

			else:
				tabwin.present_with_time(time)

			self._is_tabwin_visible = True

	def end_switching(self, do_revert=False):
		if not self._is_switching:
			return

		window = self.window
		initial_tab = self._initial_tab

		self._tabwin.hide()

		self._is_switching = False
		self._is_tabwin_visible = False
		self._initial_tab = None

		if do_revert and initial_tab:
			window.set_active_tab(initial_tab)

		else:
			tab = window.get_active_tab()

			if tab:
				self.active_tab_changed(tab, self._tab_models[tab.get_parent()])


	# tab window resizing

	def schedule_tabwin_resize(self):
		if self._tabwin_resize_id:
			return

		# need to wait a little before asking the treeview for its preferred size
		# maybe because treeview rendering is async?
		# this feels like a giant hack
		try:
			resize_id = GLib.idle_add(self.do_tabwin_resize)
		except TypeError: # gedit 3.0
			resize_id = GObject.idle_add(self.do_tabwin_resize)

		self._tabwin_resize_id = resize_id

	def cancel_tabwin_resize(self):
		if not self._tabwin_resize_id:
			return

		GLib.source_remove(self._tabwin_resize_id)

		self._tabwin_resize_id = None

	def do_tabwin_resize(self):
		view = self._view
		sw = self._sw

		view_min_size, view_nat_size = view.get_preferred_size()
		view_height = max(view_min_size.height, view_nat_size.height)

		num_rows = max(len(view.get_model()), 2)
		row_height = math.ceil(view_height / num_rows)
		max_rows_height = self.MAX_TAB_WINDOW_ROWS * row_height

		win_width, win_height = self.window.get_size()
		max_win_height = round(self.MAX_TAB_WINDOW_HEIGHT_PERCENTAGE * win_height)

		max_height = min(max_rows_height, max_win_height)

		# we can't reliably tell if overlay scrolling is being used
		# since gtk_scrolled_window_get_overlay_scrolling() can still return True if GTK_OVERLAY_SCROLLING=0 is set
		# and even if we can tell if overlay scrolling is disabled,
		# we cannot tell if the scrolled window has reserved enough space for the scrollbar
		#   fedora < 25: reserved
		#   fedora >= 25: not reserved
		#   ubuntu 17.04: reserved
		# so let's ignore overlay scrolling for now :-(

		vscrollbar_policy = Gtk.PolicyType.AUTOMATIC if view_height > max_height else Gtk.PolicyType.NEVER
		sw.set_policy(Gtk.PolicyType.NEVER, vscrollbar_policy)

		sw_min_size, sw_nat_size = sw.get_preferred_size()

		tabwin_width = max(sw_min_size.width, sw_nat_size.width)
		tabwin_height = min(view_height, max_height)

		self._tabwin.set_size_request(tabwin_width, tabwin_height)

		self._tabwin_resize_id = None

		return False


class ControlYourTabsTabModel(GObject.Object):

	__gtype_name__ = 'ControlYourTabsTabModel'

	__gsignals__ = { # gedit < 3.6
		'row-inserted': (GObject.SignalFlags.RUN_FIRST, None, (Gtk.TreePath,)),
		'row-deleted': (GObject.SignalFlags.RUN_FIRST, None, (Gtk.TreePath,)),
		'row-changed': (GObject.SignalFlags.RUN_FIRST, None, (Gtk.TreePath,)),
		'rows-reordered': (GObject.SignalFlags.RUN_FIRST, None, ()),
		'selected-path-changed': (GObject.SignalFlags.RUN_FIRST, None, (Gtk.TreePath,))
	}


	def _model_modifier(fn):
		@wraps(fn)
		def wrapper(self, *args, **kwargs):
			prev_path = self.get_selected_path()

			result = fn(self, *args, **kwargs)

			cur_path = self.get_selected_path()

			if cur_path != prev_path:
				self.emit('selected-path-changed', cur_path)

			return result

		return wrapper


	def __init__(self, tabinfo):
		GObject.Object.__init__(self)

		self._model = Gtk.ListStore.new((GdkPixbuf.Pixbuf, str, Gedit.Tab))
		self._references = {}
		self._selected = None
		self._tabinfo = tabinfo

		connect_handlers(
			self, self._model,
			[
				'row-inserted',
				'row-deleted',
				'row-changed',
				'rows-reordered'
			],
			'model'
		)

	def __len__(self):
		return len(self._model)

	def __getitem__(self, key):
		return self._model[key][2]

	@_model_modifier
	def __delitem__(self, key):
		tab = self._model[key][2]

		if self._selected == tab:
			self._selected = None

		del self._references[tab]
		del self._model[key]

	def __iter__(self):
		return [row[0] for row in self._model]

	def __contains__(self, item):
		return item in self._references

	@property
	def model(self):
		return self._model

	def on_model_row_inserted(self, model, path, iter_):
		self.emit('row-inserted', path)

	def on_model_row_deleted(self, model, path):
		self.emit('row-deleted', path)

	def on_model_row_changed(self, model, path, iter_):
		self.emit('row-changed', path)

	def on_model_rows_reordered(self, model, path, iter_, new_order):
		self.emit('rows-reordered')

	@_model_modifier
	def insert(self, position, tab):
		tab_iter = self._model.insert(
			position,
			(
				self._tabinfo.get_tab_icon(tab),
				self._tabinfo.get_tab_name(tab),
				tab
			)
		)
		self._references[tab] = Gtk.TreeRowReference.new(self._model, self._model.get_path(tab_iter))

	def append(self, tab):
		self.insert(-1, tab)

	def prepend(self, tab):
		self.insert(0, tab)

	def remove(self, tab):
		del self[self.get_path(tab)]

	@_model_modifier
	def move(self, tab, sibling, move_before):
		tab_iter = self._get_iter(tab)
		sibling_iter = self._get_iter(sibling) if sibling else None

		if move_before:
			self._model.move_before(tab_iter, sibling_iter)
		else:
			self._model.move_after(tab_iter, sibling_iter)

	def move_before(self, tab, sibling=None):
		self.move(tab, sibling, True)

	def move_after(self, tab, sibling=None):
		self.move(tab, sibling, False)

	def get_path(self, tab):
		return self._references[tab].get_path()

	def index(self, tab):
		return int(self.get_path(tab).to_string())

	def _get_iter(self, tab):
		return self._model.get_iter(self.get_path(tab))

	@_model_modifier
	def select(self, tab):
		self._selected = tab

	def unselect(self):
		self.select(None)

	def get_selected(self):
		return self._selected

	def get_selected_path(self):
		return self.get_path(self._selected) if self._selected else None

	def update(self, tab):
		path = self.get_path(tab)

		self._model[path][0] = self._tabinfo.get_tab_icon(tab)
		self._model[path][1] = self._tabinfo.get_tab_name(tab)


class ControlYourTabsConfigurable(GObject.Object, PeasGtk.Configurable):

	__gtype_name__ = 'ControlYourTabsConfigurable'


	def do_create_configure_widget(self):
		settings = get_settings()

		if settings:
			widget = Gtk.CheckButton.new_with_label(
				_("Use tabbar order for Ctrl+Tab / Ctrl+Shift+Tab")
			)

			settings.bind(
				'use-tabbar-order',
				widget, 'active',
				Gio.SettingsBindFlags.DEFAULT
			)

		else:
			label = Gtk.Label.new(
				_("Sorry, no preferences are available for this version of gedit.")
			)

			widget = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
			widget.add(label)

		widget.set_border_width(5)

		widget._settings = settings

		return widget


# this is a /hack/
# can do window.get_template_child(Gedit.Window, 'multi_notebook') since 3.12
def get_multi_notebook(tab):
	widget = tab.get_parent()

	while widget:
		if widget.__gtype__.name == 'GeditMultiNotebook':
			break

		widget = widget.get_parent()

	return widget

def get_settings():
	schemas_path = os.path.join(BASE_PATH, 'schemas')

	try:
		schema_source = Gio.SettingsSchemaSource.new_from_directory(
			schemas_path,
			Gio.SettingsSchemaSource.get_default(),
			False
		)

	except AttributeError: # gedit < 3.4
		try:
			Gedit.debug_plugin_message("relocatable schemas not supported")
		except AttributeError: # gedit < 3.4
			pass

		schema_source = None

	except:
		try:
			Gedit.debug_plugin_message("could not load settings schema source from %s", schemas_path)
		except AttributeError: # gedit < 3.4
			pass

		schema_source = None

	if not schema_source:
		return None

	schema = schema_source.lookup(
		'com.thingsthemselves.gedit.plugins.controlyourtabs',
		False
	)

	if not schema:
		return None

	return Gio.Settings.new_full(
		schema,
		None,
		'/com/thingsthemselves/gedit/plugins/controlyourtabs/'
	)

