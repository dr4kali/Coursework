import os
import time
import dpkt
import socket
import netfilterqueue
from concurrent.futures import ThreadPoolExecutor

# File paths for firewall rules and log files
RULES_FILE = "firewall_rules.txt"
LOG_FILE = "firewall_log.txt"

# Load rules once at the start to avoid repeated file I/O operations
def load_rules():
    rules = []
    with open(RULES_FILE, "r") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):  # Skip empty lines and comments
                rule_parts = [part.split(":") for part in line.strip().split(",")]
                rule_dict = {key.strip(): (None if value.strip() == "-" else (int(value.strip()) if key.strip() == "dst_port" else value.strip())) 
                             for key, value in rule_parts}
                rules.append(rule_dict)
    return rules

# Batch logging for better performance
def log_packet(packet_info_list):
    with open(LOG_FILE, "a") as log_file:
        log_file.write("\n".join(packet_info_list) + "\n")

# Generate packet log information
def generate_log_entry(packet, action, src_ip, dst_ip, proto, sport, dport):
    try:
        if proto == "TCP":
            info = f"{proto} {src_ip}:{sport} -> {dst_ip}:{dport}"
        elif proto == "UDP":
            info = f"{proto} {src_ip}:{sport} -> {dst_ip}:{dport}"
        elif proto == "ICMP":
            info = f"{proto} {src_ip} -> {dst_ip} (ICMP)"
        else:
            info = f"Unknown protocol {proto}"

        return f"{time.ctime()}: {action} {info}, {len(packet.get_payload())} bytes"
    except Exception as e:
        return f"{time.ctime()}: Error logging packet: {e}"

# Check if the packet matches the rules (optimized for clarity and efficiency)
def packet_matches(src_ip, dst_ip, proto, dport, rules):
    for rule in rules:
        if rule["src_ip"] == src_ip and rule["dst_ip"] == dst_ip and rule["protocol"] == proto:
            if proto in ["tcp", "udp"] and dport == rule["dst_port"]:
                return True
            if proto == "icmp":  # No port for ICMP
                return True
    return False

# Extract packet details using dpkt
def extract_packet_details(packet):
    ip_packet = dpkt.ip.IP(packet.get_payload())  # Convert raw packet to dpkt IP object
    src_ip = socket.inet_ntoa(ip_packet.src)
    dst_ip = socket.inet_ntoa(ip_packet.dst)
    proto = None
    sport = None
    dport = None

    # Determine protocol and destination port
    if isinstance(ip_packet.data, dpkt.tcp.TCP):
        proto = "tcp"
        sport = ip_packet.data.sport
        dport = ip_packet.data.dport
    elif isinstance(ip_packet.data, dpkt.udp.UDP):
        proto = "udp"
        sport = ip_packet.data.sport
        dport = ip_packet.data.dport
    elif isinstance(ip_packet.data, dpkt.icmp.ICMP):
        proto = "icmp"

    return src_ip, dst_ip, proto, sport, dport

# Process packet logic (to be run in parallel threads)
def process_packet_logic(packet, rules):
    try:
        # Extract packet details using dpkt
        src_ip, dst_ip, proto, sport, dport = extract_packet_details(packet)

        log_entries = []
        if proto and packet_matches(src_ip, dst_ip, proto, dport, rules):
            log_entries.append(generate_log_entry(packet, "Blocked", src_ip, dst_ip, proto.upper(), sport, dport))
            packet.drop()  # Block packet
        else:
            log_entries.append(generate_log_entry(packet, "Allowed", src_ip, dst_ip, proto.upper(), sport, dport))
            packet.accept()  # Allow packet

        # Log all actions
        log_packet(log_entries)
    except Exception as e:
        log_packet([f"{time.ctime()}: Error processing packet: {e}"])
        packet.accept()  # In case of error, allow the packet

# Callback function to process packets (parallelized)
def process_packet(packet, rules, executor):
    # Submit packet processing to the thread pool for parallel execution
    executor.submit(process_packet_logic, packet, rules)

# Set up the Netfilter Queue and bind processing function (preloads rules)
def setup_queue():
    rules = load_rules()  # Preload rules once

    queue = netfilterqueue.NetfilterQueue()
    
    # Create a thread pool to process packets in parallel
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        queue.bind(0, lambda pkt: process_packet(pkt, rules, executor))
        
        try:
            queue.run()
        except KeyboardInterrupt:
            print("Stopping firewall...")

# Main execution
if __name__ == "__main__":
    setup_queue()
