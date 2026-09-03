package com.studyedge.ai;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.os.Vibrator;
import android.util.Log;

public class StudyAlarmReceiver extends BroadcastReceiver {
    private static final String TAG = "StudyAlarmReceiver";
    public static final String CHANNEL_ID = "studyedge_alerts_channel";
    public static final String ACTION_STUDY_ALARM = "com.studyedge.ai.ALARM_TRIGGER";

    @Override
    public void onReceive(Context context, Intent intent) {
        Log.d(TAG, "Study alarm broadcast received from Android OS!");

        // Check if reminders / alarms are muted by user in DND mode
        android.content.SharedPreferences prefs = context.getSharedPreferences("StudyEdgePrefs", Context.MODE_PRIVATE);
        boolean isDnd = prefs.getBoolean("dnd_active", false);
        long dndUntil = prefs.getLong("dnd_until", 0);
        if (isDnd) {
            if (dndUntil <= 0 || System.currentTimeMillis() < dndUntil) {
                Log.d(TAG, "Study alarm strictly suppressed because reminders/alarms are muted by user (DND active). Zero sound/notification.");
                try {
                    int notifId = intent.getIntExtra("notif_id", -1);
                    if (notifId != -1) {
                        NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
                        if (nm != null) nm.cancel(notifId);
                    }
                } catch (Exception ignored) {}
                return;
            } else {
                // DND expired
                prefs.edit().putBoolean("dnd_active", false).apply();
            }
        }

        String title = intent.getStringExtra("title");
        String message = intent.getStringExtra("message");
        int notifId = intent.getIntExtra("notif_id", (int)(System.currentTimeMillis() % 100000));

        if (title == null) title = "🔔 StudyEdge Alarm";
        if (message == null) message = "Time for your study session!";

        PowerManager pm = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        PowerManager.WakeLock wakeLock = null;
        if (pm != null) {
            try {
                wakeLock = pm.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP,
                    "StudyEdge:AlarmWakeLock"
                );
                wakeLock.acquire(10000);
            } catch (Exception ignored) {}
        }

        try {
            NotificationManager nm = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "StudyEdge Study Alerts & Alarms",
                    NotificationManager.IMPORTANCE_HIGH
                );
                channel.setDescription("High-priority study alarms, reminders, and timer completions");
                channel.enableVibration(true);
                channel.setVibrationPattern(new long[]{0, 500, 250, 500, 250, 750});
                channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
                channel.setShowBadge(true);
                channel.setBypassDnd(true);

                Uri soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
                if (soundUri == null) soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
                AudioAttributes audioAttributes = new AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .build();
                channel.setSound(soundUri, audioAttributes);
                nm.createNotificationChannel(channel);
            }

            Intent launchIntent = new Intent(context, MainActivity.class);
            launchIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            int pendingFlags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                pendingFlags |= PendingIntent.FLAG_IMMUTABLE;
            }
            PendingIntent pendingIntent = PendingIntent.getActivity(context, notifId, launchIntent, pendingFlags);

            Uri soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
            if (soundUri == null) soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);

            Notification.Builder builder;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                builder = new Notification.Builder(context, CHANNEL_ID);
            } else {
                builder = new Notification.Builder(context);
                builder.setPriority(Notification.PRIORITY_MAX);
                builder.setSound(soundUri);
            }

            builder.setContentTitle(title)
                   .setContentText(message)
                   .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
                   .setContentIntent(pendingIntent)
                   .setAutoCancel(true)
                   .setVibrate(new long[]{0, 500, 250, 500, 250, 750})
                   .setDefaults(Notification.DEFAULT_ALL);

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                builder.setVisibility(Notification.VISIBILITY_PUBLIC);
                builder.setCategory(Notification.CATEGORY_ALARM);
            }

            nm.notify(notifId, builder.build());

            try {
                final android.media.Ringtone r = RingtoneManager.getRingtone(context, soundUri);
                if (r != null) {
                    r.play();
                    new android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(new Runnable() {
                        @Override
                        public void run() {
                            try { if (r.isPlaying()) r.stop(); } catch (Exception ignored) {}
                        }
                    }, 4500);
                }
            } catch (Exception ignored) {}

            try {
                Vibrator v = (Vibrator) context.getSystemService(Context.VIBRATOR_SERVICE);
                if (v != null) {
                    v.vibrate(new long[]{0, 600, 200, 600, 200, 800}, -1);
                }
            } catch (Exception ignored) {}

        } catch (Exception e) {
            Log.e(TAG, "Error firing alarm: " + e.getMessage(), e);
        }
    }
}
