package com.studyedge.ai;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.Vibrator;
import android.util.Log;
import android.view.KeyEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import android.app.AlertDialog;
import android.content.Context;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.DhcpInfo;
import android.net.wifi.WifiManager;
import android.view.Gravity;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;

public class MainActivity extends Activity {
    private static final String TAG = "StudyEdgeAI";
    private static final String CHANNEL_ID = "studyedge_alerts_channel";
    private static final String PREF_NAME = "StudyEdgePrefs";
    private static final String KEY_SERVER_URL = "server_base_url";
    private static final String DEFAULT_SERVER_URL = "http://127.0.0.1:5000";
    private static final int DISCOVERY_PORT = 5002;

    private WebView webView;
    private ProgressBar progressBar;
    private LinearLayout errorLayout;
    private TextView errorStatusText;
    private NotificationManager notifManager;
    private ScheduledExecutorService backgroundScheduler;
    private final Set<Integer> notifiedPlanIds = new HashSet<Integer>();
    private final Set<Integer> scheduledPlanIds = new HashSet<Integer>();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean isDiscovering = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED
        );

        initNotificationChannel();
        requestNotificationPermission();

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFFF3F5FF);

        webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        try {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        } catch (Exception e) {}

        // Expose JavaScript Bridge to Web App
        webView.addJavascriptInterface(new StudyEdgeBridge(this), "StudyEdgeBridge");

        progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setVisibility(View.GONE);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                if (newProgress < 100) {
                    progressBar.setVisibility(View.VISIBLE);
                    progressBar.setProgress(newProgress);
                } else {
                    progressBar.setVisibility(View.GONE);
                }
            }
        });

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                view.loadUrl(url);
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                hideErrorOverlay();
                // Inject native bridge readiness indicator
                view.evaluateJavascript("window.IS_NATIVE_ANDROID = true; if(window.onNativeBridgeReady) window.onNativeBridgeReady();", null);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                super.onReceivedError(view, request, error);
                if (request != null && request.isForMainFrame()) {
                    showErrorOverlay("Connecting to StudyEdge Server...");
                    startAutoDiscovery(false);
                }
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                super.onReceivedError(view, errorCode, description, failingUrl);
                showErrorOverlay("Connecting to StudyEdge Server...");
                startAutoDiscovery(false);
            }
        });

        root.addView(webView, new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ));
        root.addView(progressBar, new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            12
        ));

        setupErrorOverlay(root);
        setContentView(root);

        String serverBase = getServerBaseUrl();
        if (serverBase.equals(DEFAULT_SERVER_URL)) {
            startAutoDiscovery(false);
        } else {
            webView.loadUrl(serverBase + "/mobile");
        }

        startBackgroundNotificationMonitor();
    }

    private String getServerBaseUrl() {
        SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        return prefs.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL);
    }

    private void saveServerBaseUrl(String url) {
        if (url == null) return;
        url = url.trim();
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        prefs.edit().putString(KEY_SERVER_URL, url).apply();
    }

    private synchronized Set<Integer> getPersistedScheduledAlarmIds() {
        Set<Integer> ids = new HashSet<Integer>();
        try {
            SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
            String raw = prefs.getString("scheduled_alarm_ids", "");
            if (raw != null && !raw.trim().isEmpty()) {
                String[] parts = raw.split(",");
                for (String p : parts) {
                    p = p.trim();
                    if (!p.isEmpty()) {
                        ids.add(Integer.parseInt(p));
                    }
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed reading persisted alarm IDs: " + e.getMessage());
        }
        return ids;
    }

    private synchronized void addPersistedScheduledAlarmId(int id) {
        try {
            Set<Integer> ids = getPersistedScheduledAlarmIds();
            ids.add(id);
            StringBuilder sb = new StringBuilder();
            for (Integer num : ids) {
                if (sb.length() > 0) sb.append(",");
                sb.append(num);
            }
            SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
            prefs.edit().putString("scheduled_alarm_ids", sb.toString()).apply();
        } catch (Exception e) {
            Log.e(TAG, "Failed saving persisted alarm ID: " + e.getMessage());
        }
    }

    private synchronized void removePersistedScheduledAlarmId(int id) {
        try {
            Set<Integer> ids = getPersistedScheduledAlarmIds();
            if (ids.remove(id)) {
                StringBuilder sb = new StringBuilder();
                for (Integer num : ids) {
                    if (sb.length() > 0) sb.append(",");
                    sb.append(num);
                }
                SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
                prefs.edit().putString("scheduled_alarm_ids", sb.toString()).apply();
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed removing persisted alarm ID: " + e.getMessage());
        }
    }

    private synchronized void clearPersistedScheduledAlarmIds() {
        try {
            SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
            prefs.edit().remove("scheduled_alarm_ids").apply();
        } catch (Exception ignored) {}
    }

    private void setupErrorOverlay(FrameLayout root) {
        errorLayout = new LinearLayout(this);
        errorLayout.setOrientation(LinearLayout.VERTICAL);
        errorLayout.setGravity(Gravity.CENTER);
        errorLayout.setBackgroundColor(0xFF0F172A); // Slate 900
        errorLayout.setPadding(40, 40, 40, 40);
        errorLayout.setVisibility(View.GONE);

        TextView title = new TextView(this);
        title.setText("🎓 StudyEdge AI");
        title.setTextSize(24);
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER);
        errorLayout.addView(title);

        errorStatusText = new TextView(this);
        errorStatusText.setText("Connecting to StudyEdge server...");
        errorStatusText.setTextSize(14);
        errorStatusText.setTextColor(0xFF94A3B8);
        errorStatusText.setGravity(Gravity.CENTER);
        errorStatusText.setPadding(0, 20, 0, 30);
        errorLayout.addView(errorStatusText);

        ProgressBar spinner = new ProgressBar(this);
        errorLayout.addView(spinner);

        // Auto-Scan Button
        Button btnRetry = new Button(this);
        btnRetry.setText("🔍 Auto-Scan Wi-Fi");
        btnRetry.setBackgroundColor(0xFF4361EE);
        btnRetry.setTextColor(Color.WHITE);
        LinearLayout.LayoutParams lpRetry = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lpRetry.setMargins(0, 30, 0, 10);
        btnRetry.setLayoutParams(lpRetry);
        btnRetry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startAutoDiscovery(true);
            }
        });
        errorLayout.addView(btnRetry);

        // Manual IP Button
        Button btnManual = new Button(this);
        btnManual.setText("⚙️ Enter IP Manually");
        btnManual.setBackgroundColor(0xFF334155);
        btnManual.setTextColor(Color.WHITE);
        btnManual.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showManualIpDialog();
            }
        });
        errorLayout.addView(btnManual);

        root.addView(errorLayout, new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ));
    }

    private void showErrorOverlay(final String status) {
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (errorStatusText != null) errorStatusText.setText(status);
                if (errorLayout != null) errorLayout.setVisibility(View.VISIBLE);
            }
        });
    }

    private void hideErrorOverlay() {
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (errorLayout != null) errorLayout.setVisibility(View.GONE);
            }
        });
    }

    private void showManualIpDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(this);
        builder.setTitle("Enter Server IP Address");
        builder.setMessage("Enter the LAN IP shown on your laptop console (e.g. 172.20.8.157):");

        final EditText input = new EditText(this);
        String current = getServerBaseUrl().replace("http://", "").replace(":5000", "");
        input.setText(current);
        input.setSelection(input.getText().length());
        builder.setView(input);

        builder.setPositiveButton("Connect", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                String ip = input.getText().toString().trim();
                if (!ip.isEmpty()) {
                    String fullUrl = ip.startsWith("http") ? ip : "http://" + ip;
                    if (!fullUrl.contains(":5000") && !fullUrl.endsWith(".app") && !fullUrl.endsWith(".com")) {
                        fullUrl += ":5000";
                    }
                    saveServerBaseUrl(fullUrl);
                    showErrorOverlay("Connecting to " + fullUrl + "...");
                    webView.loadUrl(fullUrl + "/mobile");
                }
            }
        });
        builder.setNegativeButton("Cancel", null);
        builder.show();
    }

    private synchronized void startAutoDiscovery(final boolean forceToast) {
        if (isDiscovering) return;
        isDiscovering = true;
        showErrorOverlay("Scanning Wi-Fi & Hotspot for StudyEdge AI server...");

        Executors.newSingleThreadExecutor().execute(new Runnable() {
            @Override
            public void run() {
                final AtomicBoolean found = new AtomicBoolean(false);
                final String[] discoveredUrl = new String[1];

                // 0. Acquire Wi-Fi MulticastLock so Android OS delivers incoming UDP broadcasts
                WifiManager.MulticastLock multicastLock = null;
                try {
                    WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                    if (wifi != null) {
                        multicastLock = wifi.createMulticastLock("StudyEdgeMulticastLock");
                        multicastLock.setReferenceCounted(true);
                        multicastLock.acquire();
                    }
                } catch (Exception ignored) {}

                // 1. Instant check on previously stored server URL
                String lastSaved = getServerBaseUrl();
                if (lastSaved != null && !lastSaved.isEmpty()) {
                    if (probeStudyEdgeServer(lastSaved)) {
                        discoveredUrl[0] = lastSaved;
                        found.set(true);
                    }
                }

                // 2. Launch UDP broadcast responder probe in parallel
                final List<String> broadcastTargets = getBroadcastAddresses();
                Thread udpThread = new Thread(new Runnable() {
                    @Override
                    public void run() {
                        DatagramSocket socket = null;
                        try {
                            socket = new DatagramSocket();
                            socket.setBroadcast(true);
                            socket.setSoTimeout(3000);

                            byte[] sendData = "STUDYEDGE_DISCOVERY_REQ".getBytes();
                            for (String bcast : broadcastTargets) {
                                try {
                                    DatagramPacket sendPacket = new DatagramPacket(
                                        sendData,
                                        sendData.length,
                                        InetAddress.getByName(bcast),
                                        DISCOVERY_PORT
                                    );
                                    socket.send(sendPacket);
                                } catch (Exception ignored) {}
                            }

                            byte[] recvBuf = new byte[1024];
                            DatagramPacket recvPacket = new DatagramPacket(recvBuf, recvBuf.length);
                            socket.receive(recvPacket);

                            String message = new String(recvPacket.getData(), 0, recvPacket.getLength()).trim();
                            if (message.startsWith("STUDYEDGE_DISCOVERY_RESP:")) {
                                String url = message.substring("STUDYEDGE_DISCOVERY_RESP:".length()).trim();
                                if (found.compareAndSet(false, true)) {
                                    discoveredUrl[0] = url;
                                }
                            }
                        } catch (Exception ignored) {
                        } finally {
                            if (socket != null && !socket.isClosed()) {
                                socket.close();
                            }
                        }
                    }
                });
                udpThread.start();

                // 3. Multi-Subnet & Hotspot Parallel Socket Prober (64 worker threads)
                if (!found.get()) {
                    List<String> candidateIps = generateCandidateIps();
                    ExecutorService pool = Executors.newFixedThreadPool(64);
                    final CountDownLatch latch = new CountDownLatch(candidateIps.size());

                    for (final String ip : candidateIps) {
                        pool.execute(new Runnable() {
                            @Override
                            public void run() {
                                try {
                                    if (found.get()) return;

                                    // Rapid raw TCP socket connect (timeout 300ms)
                                    Socket s = new Socket();
                                    try {
                                        s.connect(new InetSocketAddress(ip, 5000), 300);
                                        s.close();
                                    } catch (Exception notPort5000) {
                                        return;
                                    }

                                    // Port 5000 is open! Verify it's StudyEdge
                                    String target = "http://" + ip + ":5000";
                                    if (probeStudyEdgeServer(target)) {
                                        if (found.compareAndSet(false, true)) {
                                            discoveredUrl[0] = target;
                                        }
                                    }
                                } finally {
                                    latch.countDown();
                                }
                            }
                        });
                    }

                    try {
                        latch.await(6500, TimeUnit.MILLISECONDS);
                    } catch (Exception ignored) {}
                    pool.shutdownNow();
                }

                // 4. mDNS hostname fallback
                if (!found.get()) {
                    try {
                        String mdns = "http://LAPTOP-1LUVBDO9.local:5000";
                        if (probeStudyEdgeServer(mdns)) {
                            if (found.compareAndSet(false, true)) {
                                discoveredUrl[0] = mdns;
                            }
                        }
                    } catch (Exception ignored) {}
                }

                try {
                    udpThread.join(400);
                } catch (Exception ignored) {}

                if (multicastLock != null && multicastLock.isHeld()) {
                    try { multicastLock.release(); } catch (Exception ignored) {}
                }

                final String finalDiscovered = discoveredUrl[0];
                mainHandler.post(new Runnable() {
                    @Override
                    public void run() {
                        isDiscovering = false;
                        if (finalDiscovered != null && !finalDiscovered.isEmpty()) {
                            saveServerBaseUrl(finalDiscovered);
                            Toast.makeText(MainActivity.this, "Connected: " + finalDiscovered, Toast.LENGTH_SHORT).show();
                            webView.loadUrl(finalDiscovered + "/mobile");
                        } else {
                            showErrorOverlay("Could not auto-find server on this Wi-Fi / Hotspot.\nTap below to enter IP manually.");
                            if (forceToast) {
                                Toast.makeText(MainActivity.this, "Auto-discovery timed out. Tap 'Enter IP Manually'", Toast.LENGTH_LONG).show();
                            }
                        }
                    }
                });
            }
        });
    }

    private List<String> getBroadcastAddresses() {
        List<String> list = new ArrayList<String>();
        list.add("255.255.255.255");
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface iface = interfaces.nextElement();
                if (iface.isLoopback() || !iface.isUp()) continue;
                for (java.net.InterfaceAddress addr : iface.getInterfaceAddresses()) {
                    InetAddress bcast = addr.getBroadcast();
                    if (bcast != null) {
                        String bIp = bcast.getHostAddress();
                        if (!list.contains(bIp)) list.add(bIp);
                    }
                }
            }
        } catch (Exception ignored) {}
        return list;
    }

    private boolean probeStudyEdgeServer(String baseUrl) {
        if (baseUrl == null || baseUrl.isEmpty()) return false;
        HttpURLConnection conn = null;
        try {
            while (baseUrl.endsWith("/")) {
                baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
            }
            URL url = new URL(baseUrl + "/api/host-info");
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(650);
            conn.setReadTimeout(650);
            conn.setRequestMethod("GET");
            conn.setRequestProperty("User-Agent", "StudyEdgeMobile/1.0");
            int code = conn.getResponseCode();
            if (code == 200 || code == 302) {
                return true;
            }
        } catch (Exception ignored) {
        } finally {
            if (conn != null) conn.disconnect();
        }
        return false;
    }

    private List<String> generateCandidateIps() {
        List<String> priorityList = new ArrayList<String>();
        Set<String> allSet = new HashSet<String>();

        // 1. Android ARP Cache (/proc/net/arp) - active tethered clients when phone is hotspot
        try {
            File arpFile = new File("/proc/net/arp");
            if (arpFile.exists() && arpFile.canRead()) {
                BufferedReader br = new BufferedReader(new FileReader(arpFile));
                String line;
                while ((line = br.readLine()) != null) {
                    String[] parts = line.split(" +");
                    if (parts.length >= 4 && parts[0].matches("\\d+\\.\\d+\\.\\d+\\.\\d+")) {
                        if (!parts[0].equals("0.0.0.0") && !parts[3].equals("00:00:00:00:00:00")) {
                            if (allSet.add(parts[0])) priorityList.add(parts[0]);
                        }
                    }
                }
                br.close();
            }
        } catch (Exception ignored) {}

        // 2. Wi-Fi DHCP Gateway (when phone is connected to hotspot or Wi-Fi router)
        try {
            WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wifi != null) {
                DhcpInfo dhcp = wifi.getDhcpInfo();
                if (dhcp != null && dhcp.gateway != 0) {
                    int g = dhcp.gateway;
                    String gatewayIp = String.format("%d.%d.%d.%d", (g & 0xFF), ((g >> 8) & 0xFF), ((g >> 16) & 0xFF), ((g >> 24) & 0xFF));
                    if (allSet.add(gatewayIp)) priorityList.add(gatewayIp);
                }
            }
        } catch (Exception ignored) {}

        // 3. Common Hotspot & Gateway Defaults
        String[] highPriority = {
            "192.168.43.1", "192.168.225.1", "172.20.10.1", "192.168.137.1", "192.168.42.1",
            "192.168.1.1", "192.168.0.1", "10.0.0.1", "10.0.2.2", "127.0.0.1"
        };
        for (String hp : highPriority) {
            if (allSet.add(hp)) priorityList.add(hp);
        }

        // 4. Discover Device's Real Subnets from NetworkInterface
        List<String> detectedPrefixes = new ArrayList<String>();
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces != null && interfaces.hasMoreElements()) {
                NetworkInterface iface = interfaces.nextElement();
                Enumeration<InetAddress> addresses = iface.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress addr = addresses.nextElement();
                    if (!addr.isLoopbackAddress() && addr.getHostAddress().indexOf(':') < 0) {
                        String host = addr.getHostAddress();
                        int lastDot = host.lastIndexOf('.');
                        if (lastDot > 0) {
                            String prefix = host.substring(0, lastDot + 1);
                            if (!detectedPrefixes.contains(prefix)) {
                                detectedPrefixes.add(prefix);
                            }
                            try {
                                int myHostNum = Integer.parseInt(host.substring(lastDot + 1));
                                for (int d = -30; d <= 30; d++) {
                                    int target = myHostNum + d;
                                    if (target >= 1 && target <= 254) {
                                        String ip = prefix + target;
                                        if (allSet.add(ip)) priorityList.add(ip);
                                    }
                                }
                            } catch (Exception ignored) {}
                        }
                    }
                }
            }
        } catch (Exception ignored) {}

        // 5. Hotspot clients range (.2 to .30) for common subnets
        for (int i = 2; i <= 30; i++) {
            String ip43 = "192.168.43." + i;
            String ip225 = "192.168.225." + i;
            String ip10 = "172.20.10." + i;
            String ip137 = "192.168.137." + i;
            if (allSet.add(ip43)) priorityList.add(ip43);
            if (allSet.add(ip225)) priorityList.add(ip225);
            if (allSet.add(ip10)) priorityList.add(ip10);
            if (allSet.add(ip137)) priorityList.add(ip137);
        }

        // 6. Fill in remaining subnet IPs (.1 to .254) for all detected local interfaces
        for (String prefix : detectedPrefixes) {
            for (int i = 1; i <= 254; i++) {
                String ip = prefix + i;
                if (allSet.add(ip)) priorityList.add(ip);
            }
        }

        return priorityList;
    }

    private void initNotificationChannel() {
        notifManager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "StudyEdge Study Alerts & Alarms",
                NotificationManager.IMPORTANCE_HIGH
            );
            channel.setDescription("Delivers study plan reminders, Pomodoro completion alerts, and break alarms.");
            channel.enableVibration(true);
            channel.setVibrationPattern(new long[]{0, 400, 200, 400});
            channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            if (notifManager != null) {
                notifManager.createNotificationChannel(channel);
            }
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission("android.permission.POST_NOTIFICATIONS") != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 101);
            }
        }
    }

    public void showSystemNotification(String title, String message, int id) {
        try {
            Intent intent = new Intent(this, MainActivity.class);
            intent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pendingIntent = PendingIntent.getActivity(
                this, id, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0)
            );

            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                builder = new Notification.Builder(this, CHANNEL_ID);
            } else {
                builder = new Notification.Builder(this);
                builder.setPriority(Notification.PRIORITY_HIGH);
            }

            builder.setContentTitle(title)
                   .setContentText(message)
                   .setSmallIcon(R.mipmap.ic_launcher)
                   .setContentIntent(pendingIntent)
                   .setAutoCancel(true);

            if (Build.VERSION.SDK_INT >= 21) {
                builder.setVisibility(Notification.VISIBILITY_PUBLIC);
            }

            Notification notif = builder.build();
            if (notifManager != null) {
                notifManager.notify(id, notif);
            }

            // Haptic vibration
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v != null) {
                v.vibrate(500);
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed to show notification: " + e.getMessage());
        }
    }

    private void startBackgroundNotificationMonitor() {
        backgroundScheduler = Executors.newSingleThreadScheduledExecutor();
        backgroundScheduler.scheduleWithFixedDelay(new Runnable() {
            @Override
            public void run() {
                checkDueReminders();
            }
        }, 5, 20, TimeUnit.SECONDS);
    }

    private long parseDateToMillis(String dateStr) {
        if (dateStr == null || dateStr.trim().isEmpty()) return 0;
        try {
            String clean = dateStr.replace("T", " ");
            if (clean.length() == 16) clean += ":00";
            if (clean.length() > 19) clean = clean.substring(0, 19);
            java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.US);
            java.util.Date d = sdf.parse(clean);
            return d != null ? d.getTime() : 0;
        } catch (Exception e) {
            return 0;
        }
    }

    private void checkDueReminders() {
        android.content.SharedPreferences prefs = getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
        boolean isDnd = prefs.getBoolean("dnd_active", false);
        long dndUntil = prefs.getLong("dnd_until", 0);
        if (isDnd && (dndUntil <= 0 || System.currentTimeMillis() < dndUntil)) {
            return;
        }
        HttpURLConnection conn = null;
        try {
            String baseUrl = getServerBaseUrl();
            URL url = new URL(baseUrl + "/plan/today?student_id=1");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(4000);
            conn.setReadTimeout(4000);

            int code = conn.getResponseCode();
            if (code == 200) {
                BufferedReader in = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                StringBuilder response = new StringBuilder();
                String line;
                while ((line = in.readLine()) != null) {
                    response.append(line);
                }
                in.close();

                JSONObject obj = new JSONObject(response.toString());

                // Check if server reports reminders are paused (DND)
                if (obj.optBoolean("paused", false)) {
                    int remMins = obj.optInt("remaining_minutes", 60);
                    long until = remMins == -1 ? -1 : (System.currentTimeMillis() + (remMins * 60L * 1000L));
                    StudyEdgeBridge bridge = new StudyEdgeBridge(MainActivity.this);
                    bridge.setDndActive(true, until);
                    Log.d(TAG, "Server reports reminders paused! DND activated and alarms canceled.");
                    return;
                }

                JSONArray plans = obj.optJSONArray("plans");
                if (plans != null && plans.length() > 0) {
                    long now = System.currentTimeMillis();
                    for (int i = 0; i < plans.length(); i++) {
                        JSONObject p = plans.getJSONObject(i);
                        String status = p.optString("status", "pending");
                        if (!"pending".equals(status)) continue;

                        final int planId = p.optInt("id", 0);
                        if (planId <= 0) continue;

                        String startStr = p.optString("planned_start", "");
                        long targetMillis = parseDateToMillis(startStr);
                        if (targetMillis <= 0) continue;

                        long diffSecs = (targetMillis - now) / 1000L;

                        // Case A: Upcoming plan in future -> auto-register exact OS alarm (no premature notification!)
                        if (diffSecs > 0 && !scheduledPlanIds.contains(planId)) {
                            scheduledPlanIds.add(planId);
                            final String topic = p.optString("topic", "Study Session");
                            final int mins = p.optInt("planned_duration_mins", 25);
                            StudyEdgeBridge bridge = new StudyEdgeBridge(MainActivity.this);
                            bridge.scheduleSystemAlarm(
                                "🔔 Study Reminder: " + topic,
                                "Time for your scheduled study session (" + mins + "m)! Open StudyEdge to start.",
                                diffSecs,
                                planId
                            );
                            Log.d(TAG, "Auto-registered exact OS alarm for plan " + planId + " in " + diffSecs + "s");
                        }
                        // Case B: Due right now (within -90s to 0s) -> show system alert if not notified
                        else if (diffSecs <= 0 && diffSecs >= -90 && !notifiedPlanIds.contains(planId)) {
                            notifiedPlanIds.add(planId);
                            final String topic = p.optString("topic", "Study Session");
                            mainHandler.post(new Runnable() {
                                @Override
                                public void run() {
                                    showSystemNotification(
                                        "🔔 Study Reminder: " + topic,
                                        "Starting right now! Tap to begin your focus session.",
                                        planId
                                    );
                                }
                            });
                        }
                    }
                }
            }
        } catch (Exception e) {
            // Server offline or unreachable
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    public class StudyEdgeBridge {
        private final Context context;

        public StudyEdgeBridge(Context c) {
            this.context = c;
        }

        @JavascriptInterface
        public boolean isNative() {
            return true;
        }

        @JavascriptInterface
        public void setServerUrl(final String url) {
            saveServerBaseUrl(url);
        }

        @JavascriptInterface
        public String getServerUrl() {
            return getServerBaseUrl();
        }

        @JavascriptInterface
        public void openServerConfigDialog() {
            mainHandler.post(new Runnable() {
                @Override
                public void run() {
                    showManualIpDialog();
                }
            });
        }

        @JavascriptInterface
        public void setDndActive(final boolean active, final long untilMillis) {
            try {
                android.content.SharedPreferences prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
                prefs.edit()
                     .putBoolean("dnd_active", active)
                     .putLong("dnd_until", untilMillis)
                     .apply();
                Log.d(TAG, "DND state updated: active=" + active + ", until=" + untilMillis);
                if (active) {
                    cancelAllAlarms();
                }
            } catch (Exception e) {
                Log.e(TAG, "Failed to set DND state: " + e.getMessage());
            }
        }

        @JavascriptInterface
        public void cancelAllAlarms() {
            try {
                android.app.AlarmManager am = (android.app.AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
                if (am == null) return;
                
                Set<Integer> allIds = getPersistedScheduledAlarmIds();
                allIds.addAll(scheduledPlanIds);

                for (int id : allIds) {
                    Intent intent = new Intent(context, StudyAlarmReceiver.class);
                    intent.setAction(StudyAlarmReceiver.ACTION_STUDY_ALARM);
                    int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) flags |= PendingIntent.FLAG_IMMUTABLE;
                    PendingIntent pi = PendingIntent.getBroadcast(context, id, intent, flags);
                    am.cancel(pi);
                    try {
                        pi.cancel();
                    } catch (Exception ignored) {}
                }
                scheduledPlanIds.clear();
                clearPersistedScheduledAlarmIds();
                Log.d(TAG, "All registered OS alarms strictly cancelled and cleared from preferences due to DND.");
            } catch (Exception e) {
                Log.e(TAG, "Error cancelling all alarms: " + e.getMessage());
            }
        }

        @JavascriptInterface
        public void postNotification(final String title, final String message) {
            mainHandler.post(new Runnable() {
                @Override
                public void run() {
                    showSystemNotification(title, message, (int) (System.currentTimeMillis() % 100000));
                }
            });
        }

        @JavascriptInterface
        public void vibrate(long milliseconds) {
            try {
                Vibrator v = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
                if (v != null) {
                    v.vibrate(milliseconds);
                }
            } catch (Exception ignored) {}
        }

        @JavascriptInterface
        public void scheduleSystemAlarm(final String title, final String message, final long delaySeconds, final int alarmId) {
            try {
                // If DND is active, strictly reject scheduling any system alarm!
                android.content.SharedPreferences prefs = context.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE);
                boolean isDnd = prefs.getBoolean("dnd_active", false);
                long dndUntil = prefs.getLong("dnd_until", 0);
                if (isDnd && (dndUntil <= 0 || System.currentTimeMillis() < dndUntil)) {
                    Log.d(TAG, "Refusing to schedule system alarm " + alarmId + " because reminders are currently paused/muted (DND active).");
                    return;
                }

                android.app.AlarmManager am = (android.app.AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
                if (am == null) return;

                Intent intent = new Intent(context, StudyAlarmReceiver.class);
                intent.setAction(StudyAlarmReceiver.ACTION_STUDY_ALARM);
                intent.putExtra("title", title);
                intent.putExtra("message", message);
                intent.putExtra("notif_id", alarmId);

                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    flags |= PendingIntent.FLAG_IMMUTABLE;
                }
                PendingIntent pi = PendingIntent.getBroadcast(context, alarmId, intent, flags);

                long triggerAtMillis = System.currentTimeMillis() + (delaySeconds * 1000L);

                boolean exactScheduled = false;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    try {
                        if (am.canScheduleExactAlarms()) {
                            am.setExactAndAllowWhileIdle(android.app.AlarmManager.RTC_WAKEUP, triggerAtMillis, pi);
                            exactScheduled = true;
                        }
                    } catch (SecurityException se) {
                        Log.w(TAG, "Exact alarm permission not granted; using allowWhileIdle fallback: " + se.getMessage());
                    }
                }
                if (!exactScheduled) {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        am.setAndAllowWhileIdle(android.app.AlarmManager.RTC_WAKEUP, triggerAtMillis, pi);
                    } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
                        am.setExact(android.app.AlarmManager.RTC_WAKEUP, triggerAtMillis, pi);
                    } else {
                        am.set(android.app.AlarmManager.RTC_WAKEUP, triggerAtMillis, pi);
                    }
                }
                scheduledPlanIds.add(alarmId);
                addPersistedScheduledAlarmId(alarmId);
                Log.d(TAG, "Scheduled OS exact alarm in " + delaySeconds + "s with id " + alarmId + " (persisted)");
            } catch (Exception e) {
                Log.e(TAG, "Failed to schedule system alarm: " + e.getMessage());
            }
        }

        @JavascriptInterface
        public void cancelSystemAlarm(final int alarmId) {
            try {
                android.app.AlarmManager am = (android.app.AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
                if (am == null) return;

                Intent intent = new Intent(context, StudyAlarmReceiver.class);
                intent.setAction(StudyAlarmReceiver.ACTION_STUDY_ALARM);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    flags |= PendingIntent.FLAG_IMMUTABLE;
                }
                PendingIntent pi = PendingIntent.getBroadcast(context, alarmId, intent, flags);
                am.cancel(pi);
                try {
                    pi.cancel();
                } catch (Exception ignored) {}
                scheduledPlanIds.remove(alarmId);
                removePersistedScheduledAlarmId(alarmId);
                Log.d(TAG, "Cancelled system alarm with id " + alarmId);
            } catch (Exception e) {
                Log.e(TAG, "Failed to cancel system alarm: " + e.getMessage());
            }
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView != null && webView.canGoBack()) {
            webView.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) webView.onPause();
    }

    @Override
    protected void onDestroy() {
        if (backgroundScheduler != null) {
            backgroundScheduler.shutdown();
        }
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
