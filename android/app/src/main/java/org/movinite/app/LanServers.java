package org.movinite.app;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.os.Handler;
import android.os.Looper;

import java.net.InetAddress;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 2.0.2: listen for Movinite servers advertising _movinite._tcp on the LAN (the server uses mDNS).
 * Manual entry remains the fallback when nothing is found.
 */
final class LanServers {
    static final String TYPE = "_movinite._tcp.";

    static final class Found {
        final String name;
        final String url;
        Found(String name, String url) { this.name = name; this.url = url; }
    }

    interface Listener { void onList(List<Found> list); }

    private final NsdManager nsd;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Map<String, Found> found = new LinkedHashMap<>();
    private final Listener listener;
    private NsdManager.DiscoveryListener discovery;
    private boolean running;

    LanServers(Context ctx, Listener listener) {
        this.nsd = (NsdManager) ctx.getSystemService(Context.NSD_SERVICE);
        this.listener = listener;
    }

    void start() {
        if (running || nsd == null) return;
        running = true;
        discovery = new NsdManager.DiscoveryListener() {
            @Override public void onDiscoveryStarted(String type) {}
            @Override public void onDiscoveryStopped(String type) {}
            @Override public void onStartDiscoveryFailed(String type, int code) { running = false; }
            @Override public void onStopDiscoveryFailed(String type, int code) {}
            @Override public void onServiceLost(NsdServiceInfo info) {
                synchronized (found) { found.remove(key(info)); }
                publish();
            }
            @Override public void onServiceFound(NsdServiceInfo info) {
                if (info == null || info.getServiceType() == null) return;
                if (!info.getServiceType().contains("movinite")) return;
                try {
                    nsd.resolveService(info, new NsdManager.ResolveListener() {
                        @Override public void onResolveFailed(NsdServiceInfo i, int code) {}
                        @Override public void onServiceResolved(NsdServiceInfo i) {
                            Found f = toFound(i);
                            if (f == null) return;
                            synchronized (found) { found.put(f.url, f); }
                            publish();
                        }
                    });
                } catch (Exception ignored) {}
            }
        };
        try { nsd.discoverServices(TYPE, NsdManager.PROTOCOL_DNS_SD, discovery); }
        catch (Exception e) { running = false; }
    }

    void stop() {
        if (!running) return;
        running = false;
        try { if (discovery != null) nsd.stopServiceDiscovery(discovery); } catch (Exception ignored) {}
        discovery = null;
        synchronized (found) { found.clear(); }
    }

    private void publish() {
        final List<Found> copy;
        synchronized (found) { copy = new ArrayList<>(found.values()); }
        ui.post(() -> listener.onList(copy));
    }

    private static String key(NsdServiceInfo info) {
        return info == null ? "" : String.valueOf(info.getServiceName());
    }

    private static Found toFound(NsdServiceInfo info) {
        if (info == null) return null;
        InetAddress addr = info.getHost();
        if (addr == null) return null;
        String host = addr.getHostAddress();
        if (host == null || host.isEmpty()) host = addr.getHostName();
        if (host == null || host.isEmpty()) return null;
        if (host.contains(":") && !host.startsWith("[")) host = "[" + host + "]"; // IPv6
        int port = info.getPort() > 0 ? info.getPort() : 8099;
        String url = "http://" + host + ":" + port;
        String name = info.getServiceName();
        if (name == null || name.isEmpty()) name = "Movinite";
        return new Found(name, url);
    }
}
