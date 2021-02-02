/*
 *  Adds spinner to buttons that submit a form (type="submit")
 *
 *  Usage:
 *  Add class="spinner" to button
 *
 *  Add to stylesheet:
 *  .loader { border: 3px solid #f3f3f3; border-radius: 50%; border-top: 3px solid #3498db; width: 20px; height: 20px;-webkit-animation: spin 2s linear infinite; animation: spin 2s linear infinite;}
 *  @-webkit-keyframes spin { 0% { -webkit-transform: rotate(0deg); } 100% { -webkit-transform: rotate(360deg); } }
 *  @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
 */

// Wait for DOM to finish loading
document.addEventListener('DOMContentLoaded', function() {

    // Select all forms
    document.querySelectorAll('form').forEach(item=> {

        // Call function on onsubmit event
        item.onsubmit = function() {

            // Disable all buttons
            document.querySelectorAll('button').forEach(button=> {
                button.disabled = true;
            });

            // Get text in button (with class 'spinner') where spinner should be added
            var text = item.querySelector('.spinner').innerHTML;

            // HTML - place spinner and text inline
            var HTML = `
                <div class="container">
                    <div class="row">
                        <div class="col">
                            <div class="loader"></div>
                        </div>
                        <div class="col">
            `           + text +
            `           </div>
                    </div>
                </div>
            `;

            // Replaces content of the button with HTML
            item.querySelector('.spinner').innerHTML = HTML;

        };
    });
});