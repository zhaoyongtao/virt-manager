#!/usr/bin/python

import gconf
import gtk
import gobject
import gtk.gdk
import gtk.glade
from time import time
import re
import os
import os.path
import libvirt

gconf_dir = "/apps/gnome-virtual-manager"

# Ought not to hardcode stuff as being in /usr
gladedir = "/usr/share/gnome-vm-manager"

# Hack for dev purposes
if os.path.exists("./gnome-vm-manager.glade"):
    gladedir = "."

class vmmAbout:
    def __init__(self):
        self.window = gtk.glade.XML(gladedir + "/gnome-vm-manager.glade", "vmm-about")
        self.window.get_widget("vmm-about").hide()

        self.window.signal_autoconnect({
            "on_vmm_about_delete_event": self.close,
            })

    def show(self):
        dialog = self.window.get_widget("vmm-about")
        dialog.set_version("0.1")
        dialog.show_all()

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-about").hide()
        return 1


class vmmDetails:
    def __init__(self, vmm):
        self.window = gtk.glade.XML(gladedir + "/gnome-vm-manager.glade", "vmm-details")
        self.vmm = vmm


class vmmPreferences:
    def __init__(self, conf):
        self.window = gtk.glade.XML(gladedir + "/gnome-vm-manager.glade", "vmm-preferences")
        self.conf = conf
        self.window.get_widget("vmm-preferences").hide()

        self.conf.on_stats_update_interval_changed(self.refresh_update_interval)
        self.conf.on_stats_history_length_changed(self.refresh_history_length)

        self.refresh_update_interval()
        self.refresh_history_length()

        self.window.signal_autoconnect({
            "on_stats_update_interval_changed": self.change_update_interval,
            "on_stats_history_length_changed": self.change_history_length,

            "on_close_clicked": self.close,
            "on_vmm_preferences_delete_event": self.close,
            })

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-preferences").hide()
        return 1

    def show(self):
        self.window.get_widget("vmm-preferences").show_all()

    def refresh_update_interval(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("stats-update-interval").set_value(self.conf.get_stats_update_interval())

    def refresh_history_length(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("stats-history-length").set_value(self.conf.get_stats_history_length())

    def change_update_interval(self, src):
        self.conf.set_stats_update_interval(src.get_value_as_int())

    def change_history_length(self, src):
        self.conf.set_stats_history_length(src.get_value_as_int())


class vmmManager:
    def __init__(self):
        self.window = gtk.glade.XML(gladedir + "/gnome-vm-manager.glade", "vmm-manager")
        self.conf = vmmConfig()
        self.vmm = libvirt.openReadOnly(None)
        #self.vmm = libvirt.open(None)

        self.stats = vmmStats(self.vmm, self.conf)
        self.populate_vms()
        self.about = None
        self.preferences = None

        # Setup update timers
        self.conf.on_stats_update_interval_changed(self.change_timer_interval)
        self.schedule_timer()

        self.conf.on_vmlist_status_visible_changed(self.toggle_status_visible_widget)
        self.conf.on_vmlist_cpu_usage_visible_changed(self.toggle_cpu_usage_visible_widget)
        self.conf.on_vmlist_memory_usage_visible_changed(self.toggle_memory_usage_visible_widget)
        self.conf.on_vmlist_disk_usage_visible_changed(self.toggle_disk_usage_visible_widget)
        self.conf.on_vmlist_network_traffic_visible_changed(self.toggle_network_traffic_visible_widget)

        self.window.get_widget("menu_view_status").set_active(self.conf.is_vmlist_status_visible())
        self.window.get_widget("menu_view_cpu_usage").set_active(self.conf.is_vmlist_cpu_usage_visible())
        self.window.get_widget("menu_view_memory_usage").set_active(self.conf.is_vmlist_memory_usage_visible())
        self.window.get_widget("menu_view_disk_usage").set_active(self.conf.is_vmlist_disk_usage_visible())
        self.window.get_widget("menu_view_network_traffic").set_active(self.conf.is_vmlist_network_traffic_visible())

        self.window.signal_autoconnect({
            "on_menu_view_status_activate" : self.toggle_status_visible_conf,
            "on_menu_view_cpu_usage_activate" : self.toggle_cpu_usage_visible_conf,
            "on_menu_view_memory_usage_activate" : self.toggle_memory_usage_visible_conf,
            "on_menu_view_disk_usage_activate" : self.toggle_disk_usage_visible_conf,
            "on_menu_view_network_traffic_activate" : self.toggle_network_traffic_visible_conf,

            "on_vm_manager_delete_event": self.exit_app,
            "on_menu_file_quit_activate": self.exit_app,
            "on_vmm_close_clicked": self.exit_app,

            "on_menu_edit_preferences_activate": self.show_preferences,
            "on_menu_help_about_activate": self.show_about,
            })

        self.vm_selected(None)
        self.window.get_widget("vm-list").get_selection().connect("changed", self.vm_selected)

        
    def exit_app(self, ignore=None,ignore2=None):
        gtk.main_quit()

    def schedule_timer(self):
        interval = self.conf.get_stats_update_interval() * 1000
        print "Scheduling at " + str(interval)
        self.timer_started = time() * 1000
        self.timer = gobject.timeout_add(interval, self.refresh_stats)


    def change_timer_interval(self,ignore1,ignore2,ignore3,ignore4):
        print "Removing timer"
        gobject.source_remove(self.timer)
        self.refresh_stats()
        self.schedule_timer()

    def vm_selected(self, selection):
        if selection == None or selection.count_selected_rows() == 0:
            self.window.get_widget("vm-delete").set_sensitive(False)
            self.window.get_widget("vm-details").set_sensitive(False)
            self.window.get_widget("vm-open").set_sensitive(False)
            self.window.get_widget("menu_edit_delete").set_sensitive(False)
            self.window.get_widget("menu_edit_details").set_sensitive(False)
        else:
            self.window.get_widget("vm-delete").set_sensitive(True)
            self.window.get_widget("vm-details").set_sensitive(True)
            self.window.get_widget("vm-open").set_sensitive(True)
            self.window.get_widget("menu_edit_delete").set_sensitive(True)
            self.window.get_widget("menu_edit_details").set_sensitive(True)

    def show_about(self, ignore=None):
        if self.about == None:
            self.about = vmmAbout()
        self.about.show()
            
    def show_preferences(self, ignore=None):
        if self.preferences == None:
            self.preferences = vmmPreferences(self.conf)
        self.preferences.show()
            
    def refresh_stats(self):
        self.stats.tick()

        vmlist = self.window.get_widget("vm-list")
        model = vmlist.get_model()

        for row in range(model.iter_n_children(None)):
            model.row_changed(str(row), model.iter_nth_child(None, row))

        return 1
    

    def populate_vms(self):
        vmlist = self.window.get_widget("vm-list")

        model = gtk.ListStore(str)
        vmlist.set_model(model)

        nameCol = gtk.TreeViewColumn("Name")
        statusCol = gtk.TreeViewColumn("Status")
        cpuUsageCol = gtk.TreeViewColumn("CPU usage")
        memoryUsageCol = gtk.TreeViewColumn("Memory usage")
        diskUsageCol = gtk.TreeViewColumn("Disk usage")
        networkTrafficCol = gtk.TreeViewColumn("Network traffic")

        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, 'text', 0)

        vmlist.append_column(nameCol)
        vmlist.append_column(statusCol)
        vmlist.append_column(cpuUsageCol)
        vmlist.append_column(memoryUsageCol)
        vmlist.append_column(diskUsageCol)
        vmlist.append_column(networkTrafficCol)

        status_txt = gtk.CellRendererText()
        statusCol.pack_start(status_txt, True)
        statusCol.set_cell_data_func(status_txt, self.status_text, None)
        statusCol.set_visible(self.conf.is_vmlist_status_visible())

        cpuUsage_txt = gtk.CellRendererText()
        cpuUsageCol.pack_start(cpuUsage_txt, True)
        cpuUsageCol.set_cell_data_func(cpuUsage_txt, self.cpu_usage_text, None)
        cpuUsageCol.set_visible(self.conf.is_vmlist_cpu_usage_visible())
        
        memoryUsage_txt = gtk.CellRendererText()
        memoryUsageCol.pack_start(memoryUsage_txt, True)
        memoryUsageCol.set_cell_data_func(memoryUsage_txt, self.memory_usage_text, None)
        memoryUsageCol.set_visible(self.conf.is_vmlist_memory_usage_visible())
        
        diskUsage_txt = gtk.CellRendererText()
        diskUsageCol.pack_start(diskUsage_txt, True)
        diskUsageCol.set_cell_data_func(diskUsage_txt, self.disk_usage_text, None)
        diskUsageCol.set_visible(self.conf.is_vmlist_disk_usage_visible())
        
        networkTraffic_txt = gtk.CellRendererText()
        networkTrafficCol.pack_start(networkTraffic_txt, True)
        networkTrafficCol.set_cell_data_func(networkTraffic_txt, self.network_usage_text, None)
        networkTrafficCol.set_visible(self.conf.is_vmlist_network_traffic_visible())
        
        doms = self.vmm.listDomainsID()
        if doms != None:
            for id in self.vmm.listDomainsID():
                vm = self.vmm.lookupByID(id)
                model.append([vm.name()])

    def toggle_status_visible_conf(self, menu):
        self.conf.set_vmlist_status_visible(menu.get_active())

    def toggle_status_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_status")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(1)
        col.set_visible(self.conf.is_vmlist_status_visible())

    def toggle_cpu_usage_visible_conf(self, menu):
        self.conf.set_vmlist_cpu_usage_visible(menu.get_active())

    def toggle_cpu_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_cpu_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(2)
        col.set_visible(self.conf.is_vmlist_cpu_usage_visible())

    def toggle_memory_usage_visible_conf(self, menu):
        self.conf.set_vmlist_memory_usage_visible(menu.get_active())

    def toggle_memory_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_memory_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(3)
        col.set_visible(self.conf.is_vmlist_memory_usage_visible())

    def toggle_disk_usage_visible_conf(self, menu):
        self.conf.set_vmlist_disk_usage_visible(menu.get_active())

    def toggle_disk_usage_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_disk_usage")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(4)
        col.set_visible(self.conf.is_vmlist_disk_usage_visible())

    def toggle_network_traffic_visible_conf(self, menu):
        self.conf.set_vmlist_network_traffic_visible(menu.get_active())

    def toggle_network_traffic_visible_widget(self, ignore1, ignore2, ignore3, ignore4):
        menu = self.window.get_widget("menu_view_network_traffic")
        vmlist = self.window.get_widget("vm-list")
        col = vmlist.get_column(5)
        col.set_visible(self.conf.is_vmlist_network_traffic_visible())


    def status_text(self, column, cell, model, iter, data):
        name = model.get_value(iter, 0)
        cell.set_property('text', self.stats.run_status(name))

    def cpu_usage_text(self,  column, cell, model, iter, data):
        name = model.get_value(iter, 0)
        cell.set_property('text', "%2.2f %%" % self.stats.percent_cpu_time(name))

    def memory_usage_text(self,  column, cell, model, iter, data):
        name = model.get_value(iter, 0)
        current = self.stats.current_memory(name)
        maximum = self.stats.maximum_memory(name)
        cell.set_property('text', "%s of %s" % (self.pretty_mem(current), self.pretty_mem(maximum)))
        #cell.set_property('text', self.pretty_mem(current[2]))

    def pretty_mem(self, mem):
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)

    def disk_usage_text(self,  column, cell, model, iter, data):
        #cell.set_property('text', "600 MB of 1 GB")
        cell.set_property('text', "-")

    def network_usage_text(self,  column, cell, model, iter, data):
        #cell.set_property('text', "100 bytes/sec")
        cell.set_property('text', "-")

class vmmConfig:
    def __init__(self):
        self.conf = gconf.client_get_default()
        self.conf.add_dir (gconf_dir,
                           gconf.CLIENT_PRELOAD_NONE)

    def is_vmlist_status_visible(self):
        return self.conf.get_bool(gconf_dir + "/vmlist-fields/status")

    def is_vmlist_cpu_usage_visible(self):
        return self.conf.get_bool(gconf_dir + "/vmlist-fields/cpu_usage")

    def is_vmlist_memory_usage_visible(self):
        return self.conf.get_bool(gconf_dir + "/vmlist-fields/memory_usage")

    def is_vmlist_disk_usage_visible(self):
        return self.conf.get_bool(gconf_dir + "/vmlist-fields/disk_usage")

    def is_vmlist_network_traffic_visible(self):
        return self.conf.get_bool(gconf_dir + "/vmlist-fields/network_traffic")



    def set_vmlist_status_visible(self, state):
        self.conf.set_bool(gconf_dir + "/vmlist-fields/status", state)
        
    def set_vmlist_cpu_usage_visible(self, state):
        self.conf.set_bool(gconf_dir + "/vmlist-fields/cpu_usage", state)
        
    def set_vmlist_memory_usage_visible(self, state):
        self.conf.set_bool(gconf_dir + "/vmlist-fields/memory_usage", state)
        
    def set_vmlist_disk_usage_visible(self, state):
        self.conf.set_bool(gconf_dir + "/vmlist-fields/disk_usage", state)
        
    def set_vmlist_network_traffic_visible(self, state):
        self.conf.set_bool(gconf_dir + "/vmlist-fields/network_traffic", state)



    def on_vmlist_status_visible_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/vmlist-fields/status", callback)

    def on_vmlist_cpu_usage_visible_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/vmlist-fields/cpu_usage", callback)

    def on_vmlist_memory_usage_visible_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/vmlist-fields/memory_usage", callback)

    def on_vmlist_disk_usage_visible_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/vmlist-fields/disk_usage", callback)

    def on_vmlist_network_traffic_visible_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/vmlist-fields/network_traffic", callback)



    def get_stats_update_interval(self):
        interval = self.conf.get_int(gconf_dir + "/stats/update-interval")
        if interval < 1:
            return 1
        return interval

    def get_stats_history_length(self):
        history = self.conf.get_int(gconf_dir + "/stats/history-length")
        if history < 10:
            return 10
        return history


    def set_stats_update_interval(self, interval):
        self.conf.set_int(gconf_dir + "/stats/update-interval", interval)

    def set_stats_history_length(self, length):
        self.conf.set_int(gconf_dir + "/stats/history-length", length)


    def on_stats_update_interval_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/stats/update-interval", callback)

    def on_stats_history_length_changed(self, callback):
        self.conf.notify_add(gconf_dir + "/stats/history-length", callback)


class vmmStats:
    def __init__(self, vmm, conf):
        self.vmm = vmm
        self.vms = {}
        self.conf = conf
        self.callbacks = { "notify_added": [], "notify_removed": [] }
        self.tick()

    def connect_to_signal(self, name, callback):
        if not(self.callbacks.has_key(name)):
            raise "unknown signal " + name + "requested"

        self.callbacks[name].append(callback)

    def notify_added(self, name):
        for cb in self.callbacks["notify_added"]:
            cb(name)
        

    def notify_removed(self, name):
        for cb in self.callbacks["notify_added"]:
            cb(name)

    def tick(self):
        doms = self.vmm.listDomainsID()
        newVms = {}
        if doms != None:
            for id in self.vmm.listDomainsID():
                vm = self.vmm.lookupByID(id)
                newVms[vm.name()] = vm

        for name in self.vms.keys():
            if not(newVms.has_key(name)):
                del self.vms[name]
                self.notify_removed(name)

        for name in newVms.keys():
            if not(self.vms.has_key(name)):
                self.vms[name] = { "handle": newVms[name],
                                   "stats": [] }
                self.notify_added(name)

        now = time()

        totalCpuTime = 0
        for name in self.vms.keys():
            info = self.vms[name]["handle"].info()

            if len(self.vms[name]["stats"]) > self.conf.get_stats_history_length():
                self.vms[name]["stats"] = self.vms[name]["stats"][0:len(self.vms[name]["stats"])-1]

            prevCpuTime = 0
            prevTimestamp = 0
            if len(self.vms[name]["stats"]) > 0:
                prevTimestamp = self.vms[name]["stats"][0]["timestamp"]
                prevCpuTime = self.vms[name]["stats"][0]["absCpuTime"]

            print str(now-prevTimestamp)
            print str(info[4]-prevCpuTime)
            print str((now - prevTimestamp)*1000 * 1000)
            print
            pcentCpuTime = (info[4]-prevCpuTime) * 100 / ((now - prevTimestamp)*1000 * 1000*1000)
            
            newStats = [{ "timestamp": now,
                          "status": info[0],
                          "absCpuTime": info[4],
                          "relCpuTime": (info[4]-prevCpuTime),
                          "pcentCpuTime": pcentCpuTime,
                          "currMem": info[2],
                          "maxMem": info[1] }]
            totalCpuTime = totalCpuTime + newStats[0]["relCpuTime"]
            newStats.append(self.vms[name]["stats"])
            self.vms[name]["stats"] = newStats

    def current_memory(self, name):
        return self.vms[name]["stats"][0]["currMem"]
    
    def maximum_memory(self, name):
        return self.vms[name]["stats"][0]["maxMem"]
    
    def percent_cpu_time(self, name):
        return self.vms[name]["stats"][0]["pcentCpuTime"]
    
    def run_status(self, name):
        status = self.vms[name]["stats"][0]["status"]
        if status == libvirt.VIR_DOMAIN_NOSTATE:
            return "Idle"
        elif status == libvirt.VIR_DOMAIN_RUNNING:
            return "Running"
        elif status == libvirt.VIR_DOMAIN_BLOCKED:
            return "Blocked"
        elif status == libvirt.VIR_DOMAIN_PAUSED:
            return "Paused"
        elif status == libvirt.VIR_DOMAIN_SHUTDOWN:
            return "Shutdown"
        elif status == libvirt.VIR_DOMAIN_SHUTOFF:
            return "Shutoff"
        elif status == libvirt.VIR_DOMAIN_CRASHED:
            return "Crashed"
        else:
            raise "Unknown status code"
    
        
# Run me!
def main():
    window = vmmManager()
    gtk.main()

if __name__ == "__main__":
    main()
