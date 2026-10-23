package pk.quantofrehan;

import android.content.Context;
import android.util.AttributeSet;
import android.widget.Spinner;

/**
 * The console's one dropdown (owner order 2026-10-23, 2.0.0): every dropdown
 * carries an arrow beside it, pointed DOWN while the menu is closed (the
 * pull-down cue) and UP while it is open (the pull-up cue).
 *
 * Spinner has no public popup state, so this subclass reports the two edges
 * the platform does give: <code>performClick</code> when the menu opens, and
 * <code>onWindowFocusChanged</code> with focus back when it closes (the
 * menu's own window holds the focus while it is up, so the focus returning
 * to the activity IS the close edge). The arrow is a view beside the
 * dropdown, driven from MainActivity, so the styles row never has to know
 * about it and the three dropdowns share one law.
 */
public class Dropdown extends Spinner {

    /** The listener one MainActivity wire-up gives every dropdown. */
    public interface OpenListener {
        void onDropdownOpenChange(boolean open);
    }

    private OpenListener openListener;

    public Dropdown(Context context) {
        super(context);
    }

    public Dropdown(Context context, int mode) {
        super(context, mode);
    }

    public Dropdown(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public Dropdown(Context context, AttributeSet attrs, int defStyleAttr) {
        super(context, attrs, defStyleAttr);
    }

    public void setOpenListener(OpenListener listener) {
        openListener = listener;
    }

    @Override
    public boolean performClick() {
        boolean handled = super.performClick();
        if (openListener != null) {
            openListener.onDropdownOpenChange(true);
        }
        return handled;
    }

    @Override
    public void onWindowFocusChanged(boolean hasWindowFocus) {
        super.onWindowFocusChanged(hasWindowFocus);
        // Only the focus REGAINING is a close: opening the menu also takes
        // the activity's focus away first, so a focus loss cannot tell the
        // two edges apart, and the performClick above already reported the
        // open. Focus back with performClick never fired on it is the close.
        if (hasWindowFocus && openListener != null) {
            openListener.onDropdownOpenChange(false);
        }
    }
}
