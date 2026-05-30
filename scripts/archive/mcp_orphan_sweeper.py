import psutil
import time
import sys

def get_mcp_orphans():
    orphans = []
    now = time.time()
    mcp_keywords = ['workspace-mcp', 'ms-365-mcp']
    my_pid = psutil.Process().pid
    
    for proc in psutil.process_iter(['pid', 'ppid', 'cmdline', 'create_time', 'terminal']):
        try:
            info = proc.info
            cmdline = " ".join(info['cmdline']) if info['cmdline'] else ""
            
            if any(k in cmdline for k in mcp_keywords):
                if proc.pid == my_pid:
                    continue
                
                if info['ppid'] == 1:
                    orphans.append(proc)
                elif info['terminal'] is None and (now - info['create_time']) > 3600:
                    orphans.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return orphans

if __name__ == "__main__":
    orphans = get_mcp_orphans()
    print(f"Found {len(orphans)} orphan processes.")
    
    killed_count = 0
    saved_mem = 0
    for p in orphans:
        try:
            # Use memory_info() instead of 'rss' attribute in process_iter
            mem = p.memory_info().rss
            p.kill()
            saved_mem += mem
            killed_count += 1
            print(f"Killed PID {p.pid} (Saved {mem/1024/1024:.2f} MB)")
        except Exception as e:
            print(f"Failed to kill PID {p.pid}: {e}")
            
    print(f"Cleaned {killed_count} processes. Total memory recovered: {saved_mem/1024/1024:.2f} MB")
