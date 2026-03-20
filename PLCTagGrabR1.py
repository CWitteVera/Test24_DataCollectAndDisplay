import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from datetime import datetime
import threading
import time
from collections import defaultdict
from pylogix import PLC
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates

class PLCTagReader:
    # Configuration constants
    MAX_DATA_POINTS = 5000  # Maximum data points stored per tag (change this to increase/decrease)
    
    def __init__(self, root):
        self.root = root
        self.root.title("PLC Tag Reader - Multiple Tags & Polling")
        self.root.geometry("1200x700")
        
        self.config_file = "plc_config.json"
        self.config = self.load_config()
        
        self.plc = None
        self.polling = False
        self.poll_interval = 1.0  # seconds
        self.poll_thread = None
        self.monitor_queue = []  # Queue for thread-safe updates
        
        # Data storage: {tag_name: [(datetime, value), ...]}
        self.tag_data = defaultdict(list)
        
        # Active tags being monitored
        self.active_tags = set()
        
        # Tag pairs for bar graph: {pair_name: {increase_tag, decrease_tag, current_value}}
        self.tag_pairs = {}
        
        # Track previous state for edge detection
        self.previous_state = {}
        
        # Track pulse counts per tag
        self.pulse_counts = {}
        
        self.setup_ui()
        
        # Load persisted tags and pairs
        self.load_persisted_items()
        
    def load_config(self):
        """Load saved IP addresses and settings"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    # Initialize pulse counts from config
                    if 'pulse_counts' in config:
                        self.pulse_counts = config['pulse_counts']
                    return config
            except:
                return {"ip_addresses": [], "last_ip": "", "active_tags": [], "tag_pairs": {}, "pulse_counts": {}}
        return {"ip_addresses": [], "last_ip": "", "active_tags": [], "tag_pairs": {}, "pulse_counts": {}}
    
    def save_config(self):
        """Save IP addresses and settings"""
        self.config['pulse_counts'] = self.pulse_counts
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def add_ip_to_history(self, ip):
        """Add IP to history and save"""
        if ip and ip not in self.config["ip_addresses"]:
            self.config["ip_addresses"].insert(0, ip)
            if len(self.config["ip_addresses"]) > 10:
                self.config["ip_addresses"].pop()
        self.config["last_ip"] = ip
        self.save_config()
        self.update_ip_dropdown()
    
    def update_ip_dropdown(self):
        """Update the IP address dropdown"""
        self.ip_combo['values'] = self.config["ip_addresses"]
    
    def load_persisted_items(self):
        """Load saved tags and pairs from config"""
        # Load tags
        for tag in self.config.get("active_tags", []):
            if tag and tag not in self.active_tags:
                self.active_tags.add(tag)
                self.items_listbox.insert(tk.END, f"📊 TAG: {tag}")
                self.tag_data[tag] = []
        
        # Load pairs
        for pair_name, pair_config in self.config.get("tag_pairs", {}).items():
            if pair_name not in self.tag_pairs:
                self.tag_pairs[pair_name] = {
                    'increase_tag': pair_config.get('increase_tag', ''),
                    'decrease_tag': pair_config.get('decrease_tag', ''),
                    'current_value': 0
                }
                inc_tag = pair_config.get('increase_tag', '')
                dec_tag = pair_config.get('decrease_tag', '')
                self.items_listbox.insert(tk.END, f"📈 PAIR: {pair_name} (↑{inc_tag} ↓{dec_tag})")
    
    def setup_ui(self):
        """Create the user interface with toolbar and three-panel layout.

        Left: configuration. Center: live monitor. Right: live bar graph.
        """
        # Basic style adjustments
        style = ttk.Style()
        try:
            style.configure('.', font=('Segoe UI', 10))
        except Exception:
            pass

        # Top toolbar
        toolbar = ttk.Frame(self.root, padding=(6, 4))
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text='Start', command=self.start_polling).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text='Stop', command=self.stop_polling).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text='Test Tag', command=self.test_tag).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text='Refresh Graph', command=self.refresh_graph).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text='Reset Pulses', command=self.reset_pulse_counts).pack(side=tk.LEFT, padx=4)

        # Status pill on toolbar
        self.status_pill = tk.Label(toolbar, text='Idle', bg='#f0f0f0', fg='#333', padx=8, pady=2)
        self.status_pill.pack(side=tk.RIGHT, padx=8)

        # Main panes: left config, right (monitor above graph)
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_pane, width=380)
        right_pane = ttk.PanedWindow(main_pane, orient=tk.VERTICAL)

        main_pane.add(left_frame, weight=1)
        main_pane.add(right_pane, weight=3)

        monitor_frame = ttk.Frame(right_pane)
        graph_frame = ttk.Frame(right_pane)
        right_pane.add(monitor_frame, weight=2)
        right_pane.add(graph_frame, weight=3)

        # Assign frames used by existing setup functions
        self.config_frame = left_frame
        self.monitor_frame = monitor_frame
        self.data_frame = graph_frame

        # Build the panels
        self.setup_config_tab()
        self.setup_monitor_tab()
        self.setup_graph_tab()

        # Keyboard shortcuts
        self.root.bind('<Control-s>', lambda e: self.start_polling())
        self.root.bind('<Control-t>', lambda e: self.stop_polling())
        self.root.bind('<Control-r>', lambda e: self.refresh_graph())
        self.root.bind('<Control-e>', lambda e: self.test_tag())
    
    def setup_config_tab(self):
        """Setup the configuration tab with consolidated tag/pair list"""
        main = ttk.Frame(self.config_frame, padding="8")
        main.pack(fill=tk.BOTH, expand=True)
        
        # IP Address section
        ttk.Label(main, text="PLC IP Address:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky=tk.W, pady=8)
        
        ip_frame = ttk.Frame(main)
        ip_frame.grid(row=0, column=1, sticky=tk.EW, padx=5)
        
        self.ip_combo = ttk.Combobox(ip_frame, width=28, values=self.config["ip_addresses"])
        self.ip_combo.set(self.config["last_ip"])
        self.ip_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(ip_frame, text="Test", command=self.test_connection, width=6).pack(side=tk.LEFT, padx=2)
        
        # Polling Interval
        ttk.Label(main, text="Poll Interval (ms):", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky=tk.W, pady=8)
        
        self.interval_var = tk.DoubleVar(value=1000.0)
        ttk.Spinbox(main, from_=1, to=60000, textvariable=self.interval_var, width=12).grid(row=1, column=1, sticky=tk.W, padx=5)
        
        # Separator
        ttk.Separator(main, orient=tk.HORIZONTAL).grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=12)
        
        # Tags section
        ttk.Label(main, text="Add Tag:", font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky=tk.W, pady=(8, 4))
        
        tag_frame = ttk.Frame(main)
        tag_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW, padx=0, pady=(0, 8))
        
        self.new_tag_entry = ttk.Entry(tag_frame, width=20)
        self.new_tag_entry.pack(side=tk.LEFT, padx=(0, 4), fill=tk.X, expand=True)
        
        ttk.Button(tag_frame, text="Add", command=self.add_tag, width=5).pack(side=tk.LEFT, padx=2)
        
        # Pair section
        ttk.Label(main, text="Add Pair:", font=("Segoe UI", 9, "bold")).grid(row=5, column=0, sticky=tk.W, pady=(8, 4))
        
        pair_frame = ttk.Frame(main)
        pair_frame.grid(row=6, column=0, columnspan=2, sticky=tk.EW, padx=0, pady=(0, 8))
        
        ttk.Label(pair_frame, text="Name").pack(side=tk.LEFT, padx=(0, 2))
        self.pair_name_entry = ttk.Entry(pair_frame, width=10)
        self.pair_name_entry.pack(side=tk.LEFT, padx=(0, 6))
        
        ttk.Label(pair_frame, text="Inc↑").pack(side=tk.LEFT, padx=(0, 2))
        self.inc_tag_entry = ttk.Entry(pair_frame, width=10)
        self.inc_tag_entry.pack(side=tk.LEFT, padx=(0, 6))
        
        ttk.Label(pair_frame, text="Dec↓").pack(side=tk.LEFT, padx=(0, 2))
        self.dec_tag_entry = ttk.Entry(pair_frame, width=10)
        self.dec_tag_entry.pack(side=tk.LEFT, padx=(0, 6))
        
        ttk.Button(pair_frame, text="Add", command=self.add_tag_pair, width=5).pack(side=tk.LEFT, padx=2)
        
        # Consolidated list
        ttk.Label(main, text="Monitored Items:", font=("Segoe UI", 9, "bold")).grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(12, 4))
        
        list_frame = ttk.Frame(main)
        list_frame.grid(row=8, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=0, pady=(0, 8))
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.items_listbox = tk.Listbox(list_frame, height=12, yscrollcommand=scrollbar.set, font=("Segoe UI", 9))
        self.items_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.items_listbox.yview)
        
        # Remove button
        ttk.Button(main, text="Remove Selected", command=self.remove_item).grid(row=9, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
        
        main.columnconfigure(1, weight=1)
        main.rowconfigure(8, weight=1)
    
    def setup_monitor_tab(self):
        """Setup the current readings display with two-column layout"""
        main = ttk.Frame(self.monitor_frame, padding="10")
        main.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main, text="Current Readings", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))
        
        # Two-column container
        columns_frame = ttk.Frame(main)
        columns_frame.pack(fill=tk.BOTH, expand=True)
        
        # Left column - Tags
        left_frame = ttk.Frame(columns_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        ttk.Label(left_frame, text="Tags", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 4))
        
        left_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tags_text = tk.Text(left_frame, height=20, width=25, wrap=tk.WORD, 
                                 font=("Segoe UI", 10), yscrollcommand=left_scroll.set, bg="#f8f8f8")
        self.tags_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left_scroll.config(command=self.tags_text.yview)
        
        self.tags_text.tag_config("tag_name", foreground="#0066cc", font=("Segoe UI", 10, "bold"))
        self.tags_text.tag_config("tag_value", foreground="#009900", font=("Segoe UI", 10))
        self.tags_text.tag_config("pulse_count", foreground="#ff6600", font=("Segoe UI", 9, "italic"))
        self.tags_text.config(state=tk.DISABLED)
        
        # Right column - Pairs
        right_frame = ttk.Frame(columns_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        ttk.Label(right_frame, text="Pair Counts", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 4))
        
        right_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL)
        right_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.pairs_text = tk.Text(right_frame, height=20, width=25, wrap=tk.WORD, 
                                  font=("Segoe UI", 10), yscrollcommand=right_scroll.set, bg="#f8f8f8")
        self.pairs_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_scroll.config(command=self.pairs_text.yview)
        
        self.pairs_text.tag_config("pair_name", foreground="#cc6600", font=("Segoe UI", 10, "bold"))
        self.pairs_text.tag_config("pair_value", foreground="#ff6600", font=("Segoe UI", 10))
        self.pairs_text.tag_config("total", foreground="#ff0000", font=("Segoe UI", 11, "bold"))
        self.pairs_text.config(state=tk.DISABLED)
    
    def setup_graph_tab(self):
        """Setup the graph tab"""
        main = ttk.Frame(self.data_frame, padding="10")
        main.pack(fill=tk.BOTH, expand=True)
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(12, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=main)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Refresh button
        ttk.Button(main, text="Refresh Graph", command=self.refresh_graph).pack(pady=5)
        
    def test_connection(self):
        """Test connection to PLC"""
        ip = self.ip_combo.get().strip()
        if not ip:
            messagebox.showerror("Error", "Please enter an IP address")
            return
        
        try:
            plc = PLC()
            plc.IPAddress = ip
            # Try to read a simple tag or just establish connection
            result = plc.Read("test")
            self.add_ip_to_history(ip)
            messagebox.showinfo("Success", f"Connection to {ip} successful!")
        except Exception as e:
            messagebox.showerror("Connection Failed", f"Error: {str(e)}")
    
    def add_tag(self):
        """Add a tag to monitor"""
        tag = self.new_tag_entry.get().strip()
        if not tag:
            messagebox.showerror("Error", "Please enter a tag name")
            return
        
        if tag in self.active_tags:
            messagebox.showwarning("Duplicate", "This tag is already being monitored")
            return
        
        self.active_tags.add(tag)
        self.items_listbox.insert(tk.END, f"📊 TAG: {tag}")
        self.new_tag_entry.delete(0, tk.END)
        self.tag_data[tag] = []  # Initialize data list
        
        # Save to config
        self.config["active_tags"] = list(self.active_tags)
        self.save_config()
    
    def test_tag(self):
        """Test reading a specific tag"""
        ip = self.ip_combo.get().strip()
        tag = self.new_tag_entry.get().strip()
        
        if not ip:
            messagebox.showerror("Error", "Please enter a PLC IP address first")
            return
        
        if not tag:
            messagebox.showerror("Error", "Please enter a tag name to test")
            return
        
        try:
            plc = PLC()
            plc.IPAddress = ip
            result = plc.Read(tag)
            
            if str(result.Status) == "Success":
                messagebox.showinfo("Success", f"Tag '{tag}' read successfully!\n\nValue: {result.Value}\nType: {type(result.Value).__name__}")
            else:
                messagebox.showerror("Read Failed", f"Failed to read tag '{tag}'\n\nStatus: {result.Status}")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Error: {str(e)}")
    
    def remove_tag(self):
        """Remove selected tag from monitoring"""
        selection = self.items_listbox.curselection()
        if selection:
            item_text = self.items_listbox.get(selection[0])
            if "TAG:" in item_text:
                tag = item_text.replace("📊 TAG: ", "").strip()
                self.active_tags.discard(tag)
                self.items_listbox.delete(selection[0])
                if tag in self.tag_data:
                    del self.tag_data[tag]
                
                # Save to config
                self.config["active_tags"] = list(self.active_tags)
                self.save_config()
    
    def add_tag_pair(self):
        """Add a tag pair for bar graph and auto-add the tags"""
        pair_name = self.pair_name_entry.get().strip()
        inc_tag = self.inc_tag_entry.get().strip()
        dec_tag = self.dec_tag_entry.get().strip()
        
        if not pair_name:
            messagebox.showerror("Error", "Please enter a pair name")
            return
        
        if not inc_tag or not dec_tag:
            messagebox.showerror("Error", "Please enter both increase and decrease tag names")
            return
        
        if pair_name in self.tag_pairs:
            messagebox.showwarning("Duplicate", "This pair name already exists")
            return
        
        self.tag_pairs[pair_name] = {
            'increase_tag': inc_tag,
            'decrease_tag': dec_tag,
            'current_value': 0
        }
        self.items_listbox.insert(tk.END, f"📈 PAIR: {pair_name} (↑{inc_tag} ↓{dec_tag})")
        
        # Auto-add the tags if they don't exist
        for tag in [inc_tag, dec_tag]:
            if tag and tag not in self.active_tags:
                self.active_tags.add(tag)
                self.items_listbox.insert(tk.END, f"📊 TAG: {tag}")
                self.tag_data[tag] = []
        
        self.pair_name_entry.delete(0, tk.END)
        self.inc_tag_entry.delete(0, tk.END)
        self.dec_tag_entry.delete(0, tk.END)
        
        # Save to config
        self.config["active_tags"] = list(self.active_tags)
        self.config["tag_pairs"] = {
            name: {'increase_tag': cfg['increase_tag'], 'decrease_tag': cfg['decrease_tag']}
            for name, cfg in self.tag_pairs.items()
        }
        self.save_config()
    
    def remove_tag_pair(self):
        """Remove selected tag pair"""
        selection = self.items_listbox.curselection()
        if selection:
            item_text = self.items_listbox.get(selection[0])
            if "PAIR:" in item_text:
                pair_name = item_text.split("PAIR:")[1].split("(")[0].strip()
                if pair_name in self.tag_pairs:
                    del self.tag_pairs[pair_name]
                self.items_listbox.delete(selection[0])
                
                # Save to config
                self.config["tag_pairs"] = {
                    name: {'increase_tag': cfg['increase_tag'], 'decrease_tag': cfg['decrease_tag']}
                    for name, cfg in self.tag_pairs.items()
                }
                self.save_config()
    
    def remove_item(self):
        """Remove selected item (tag or pair)"""
        selection = self.items_listbox.curselection()
        if selection:
            item_text = self.items_listbox.get(selection[0])
            if "TAG:" in item_text:
                self.remove_tag()
            elif "PAIR:" in item_text:
                self.remove_tag_pair()
    
    def start_polling(self):
        """Start polling tags"""
        ip = self.ip_combo.get().strip()
        if not ip:
            messagebox.showerror("Error", "Please enter an IP address")
            return
        
        if not self.active_tags:
            messagebox.showerror("Error", "Please add at least one tag to monitor")
            return
        
        self.add_ip_to_history(ip)
        self.poll_interval = self.interval_var.get() / 1000.0  # Convert milliseconds to seconds
        self.polling = True
        self.monitor_queue = []  # Clear queue
        
        # Initialize previous_state with current tag values to avoid false rising edges on start
        try:
            plc = PLC()
            plc.IPAddress = ip
            self.previous_state = {}
            
            # Read all tags once to initialize state
            for tag in list(self.active_tags):
                result = plc.Read(tag)
                if str(result.Status) == "Success":
                    self.previous_state[tag] = result.Value
                else:
                    self.previous_state[tag] = False
            
            # Initialize pair tags
            for pair_name, pair_config in self.tag_pairs.items():
                inc_tag = pair_config['increase_tag']
                dec_tag = pair_config['decrease_tag']
                if inc_tag not in self.previous_state:
                    inc_result = plc.Read(inc_tag)
                    self.previous_state[inc_tag] = inc_result.Value if str(inc_result.Status) == "Success" else False
                if dec_tag not in self.previous_state:
                    dec_result = plc.Read(dec_tag)
                    self.previous_state[dec_tag] = dec_result.Value if str(dec_result.Status) == "Success" else False
        except:
            self.previous_state = {}  # Fallback if init fails
        
        self.status_pill.config(text="Polling", bg="#4CAF50", fg="white")
        
        self.poll_thread = threading.Thread(target=self.poll_loop, daemon=True)
        self.poll_thread.start()
        
        # Start processing monitor queue updates
        self.root.after(500, self.process_monitor_queue)
    
    def stop_polling(self):
        """Stop polling tags"""
        self.polling = False
        self.status_pill.config(text="Idle", bg="#f0f0f0", fg="#333")
    
    def poll_loop(self):
        """Background polling loop"""
        ip = self.ip_combo.get().strip()
        plc = PLC()
        plc.IPAddress = ip
        
        while self.polling:
            try:
                timestamp = datetime.now()
                poll_data = {}
                
                # Store current readings for pulse counting LATER
                current_tag_values = {}
                
                # Read all active tags
                for tag in list(self.active_tags):
                    result = plc.Read(tag)
                    
                    if str(result.Status) == "Success":
                        value = result.Value
                        poll_data[tag] = value
                        current_tag_values[tag] = value
                        
                        # Store data point
                        self.tag_data[tag].append((timestamp, value))
                        
                        # Keep only last MAX_DATA_POINTS data points per tag
                        if len(self.tag_data[tag]) > self.MAX_DATA_POINTS:
                            self.tag_data[tag].pop(0)
                
                # Read all tags used in pairs FIRST (before processing any pair)
                pair_tag_values = {}
                for pair_name, pair_config in self.tag_pairs.items():
                    inc_tag = pair_config['increase_tag']
                    dec_tag = pair_config['decrease_tag']
                    
                    # Read and cache tag values if not already read
                    if inc_tag not in pair_tag_values:
                        inc_result = plc.Read(inc_tag)
                        if str(inc_result.Status) == "Success":
                            pair_tag_values[inc_tag] = inc_result.Value
                        else:
                            pair_tag_values[inc_tag] = None
                    
                    if dec_tag not in pair_tag_values:
                        dec_result = plc.Read(dec_tag)
                        if str(dec_result.Status) == "Success":
                            pair_tag_values[dec_tag] = dec_result.Value
                        else:
                            pair_tag_values[dec_tag] = None
                
                # THEN process all pairs using cached values
                for pair_name, pair_config in self.tag_pairs.items():
                    inc_tag = pair_config['increase_tag']
                    dec_tag = pair_config['decrease_tag']
                    
                    # Process increase tag
                    if inc_tag in pair_tag_values and pair_tag_values[inc_tag] is not None:
                        inc_value = pair_tag_values[inc_tag]
                        prev_inc = self.previous_state.get(inc_tag, False)
                        if not prev_inc and inc_value:  # Rising edge
                            self.tag_pairs[pair_name]['current_value'] += 1
                            poll_data[f"{pair_name}_inc"] = "↑"
                    
                    # Process decrease tag
                    if dec_tag in pair_tag_values and pair_tag_values[dec_tag] is not None:
                        dec_value = pair_tag_values[dec_tag]
                        prev_dec = self.previous_state.get(dec_tag, False)
                        if not prev_dec and dec_value:  # Rising edge
                            self.tag_pairs[pair_name]['current_value'] -= 1
                            poll_data[f"{pair_name}_dec"] = "↓"
                
                # NOW update previous state after all pairs are processed
                # But save the old state first for pulse counting
                old_previous_state = dict(self.previous_state)
                self.previous_state.update(pair_tag_values)
                
                # Track pulse counts for all tags (independent of pair logic)
                for tag in current_tag_values:
                    value = current_tag_values[tag]
                    if isinstance(value, bool):
                        # Use old previous state for pulse detection
                        prev_state = old_previous_state.get(tag, False)
                        if not prev_state and value:  # Rising edge
                            if tag not in self.pulse_counts:
                                self.pulse_counts[tag] = 0
                            self.pulse_counts[tag] += 1
                        # Update the state for next iteration
                        self.previous_state[tag] = value
                
                # Update monitor display
                self.update_monitor_display(timestamp, poll_data)
                
                time.sleep(self.poll_interval)
                
            except Exception as e:
                error_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}\n"
                self.monitor_queue.append(('error', error_msg))
                time.sleep(self.poll_interval)
    
    def update_monitor_display(self, timestamp, poll_data):
        """Update current readings display (thread-safe)"""
        self.monitor_queue.append(('readings', poll_data))
    
    def process_monitor_queue(self):
        """Process queued updates from background thread (thread-safe)"""
        while self.monitor_queue:
            item = self.monitor_queue.pop(0)
            if item[0] == 'readings':
                self.update_readings_display(item[1])
        
        # Auto-refresh graph every 500ms if polling
        try:
            if self.polling and self.tag_pairs:
                self.refresh_graph()
        except:
            pass
        
        if self.polling:
            self.root.after(500, self.process_monitor_queue)
    
    def update_readings_display(self, poll_data):
        """Update the readings text display with current values - split into two columns"""
        # Update left column - Tags
        self.tags_text.config(state=tk.NORMAL)
        self.tags_text.delete(1.0, tk.END)
        
        if self.active_tags:
            for tag in sorted(self.active_tags):
                value = poll_data.get(tag, "N/A")
                pulse_count = self.pulse_counts.get(tag, 0)
                self.tags_text.insert(tk.END, f"{tag}: ", "tag_name")
                self.tags_text.insert(tk.END, f"{value} ", "tag_value")
                self.tags_text.insert(tk.END, f"[{pulse_count}]\n", "pulse_count")
        else:
            self.tags_text.insert(tk.END, "No tags monitored", "tag_name")
        
        self.tags_text.config(state=tk.DISABLED)
        
        # Update right column - Pairs
        self.pairs_text.config(state=tk.NORMAL)
        self.pairs_text.delete(1.0, tk.END)
        
        if self.tag_pairs:
            for pair_name in sorted(self.tag_pairs.keys()):
                value = self.tag_pairs[pair_name]['current_value']
                self.pairs_text.insert(tk.END, f"{pair_name}: ", "pair_name")
                self.pairs_text.insert(tk.END, f"{value}\n", "pair_value")
        else:
            self.pairs_text.insert(tk.END, "No pairs configured", "pair_name")
        
        self.pairs_text.config(state=tk.DISABLED)
    
    def refresh_graph(self):
        """Refresh the graph with current bar data"""
        if not self.tag_pairs:
            messagebox.showwarning("No Data", "No tag pairs configured yet. Add pairs in the Configuration tab.")
            return
        
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        # Prepare data
        pair_names = list(self.tag_pairs.keys())
        values = [self.tag_pairs[pair]['current_value'] for pair in pair_names]
        
        # Create bar chart
        colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#34495e']
        bar_colors = [colors[i % len(colors)] for i in range(len(pair_names))]
        
        bars = ax.bar(pair_names, values, color=bar_colors, edgecolor='black', linewidth=2)
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(height)}',
                   ha='center', va='bottom', fontweight='bold', fontsize=12)
        
        ax.set_ylabel('Value', fontsize=12, fontweight='bold')
        ax.set_title('Live Tag Pair Values', fontsize=14, fontweight='bold')
        
        # Stable y-axis scaling: calculate max range and add 20% padding
        max_value = max(values) if values else 0
        min_value = min(values) if values else 0
        value_range = max(abs(max_value), abs(min_value))
        
        # Set y-axis with padding (20% above/below)
        padding = value_range * 0.2 if value_range > 0 else 10
        ax.set_ylim(min_value - padding, max_value + padding)
        
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        self.figure.tight_layout()
        self.canvas.draw()
    
    def reset_pulse_counts(self):
        """Reset all pulse counts to zero"""
        if not self.pulse_counts:
            messagebox.showinfo("No Pulses", "No pulse counts to reset.")
            return
        
        self.pulse_counts.clear()
        self.save_config()
        messagebox.showinfo("Success", "All pulse counts reset to zero.")
        self.process_monitor_queue()  # Trigger immediate display update


if __name__ == "__main__":
    root = tk.Tk()
    app = PLCTagReader(root)
    root.mainloop()
