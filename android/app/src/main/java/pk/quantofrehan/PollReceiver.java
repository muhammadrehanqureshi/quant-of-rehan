package pk.quantofrehan;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Re-arms and beats the watchdog: on alarms and after phone restarts. */
public class PollReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? "" : intent.getAction();
        if (action != null && action.equals(Intent.ACTION_BOOT_COMPLETED)) {
            Watcher.kick(context);
        } else {
            Watcher.beat(context);
            Watcher.armAlarms(context);
        }
    }
}
