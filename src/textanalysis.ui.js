"use strict"

define(['jquery', 'autocomplete', 'rz_core', 'textanalysis', 'signal', 'consts'],
function($, autocomplete, rz_core, textanalysis, signal, consts) {

var text = ""; // Last text of sentence
var element_name = '#textanalyser';
var element = $(element_name);
var suggestionChange;

var typeselection = function TypeSelectionDialog() {
    var e = $('.typeselection'),
        typeselection = {};

    typeselection.analysisNodeStart = function() {
        typeselection.show();
        e.html('<table><tr><td style="height:28px"></td></tr><tr><td>Use [TAB] key to pick a type</td></tr></table>');
    }
    typeselection.show = function() {
        e.css({
            top: window.innerHeight/2-115,
            left: window.innerWidth/2-325});
    }
    typeselection.hide = function() {
        e.css('top', -300);
        e.css('left', 0);
    }
    typeselection.showChosenType = function(nodetype) {
        e.html('<table><tr><td style="height:28px"></td></tr><tr><td>' + "Chosen Type: " + nodetype + '</td></tr></table>');
    }
    return typeselection;
}();

function analyzeSentence(sentence, finalize)
{
    var ret = textanalysis.textAnalyser(sentence, finalize);

    switch (ret.state) {
    case textanalysis.ANALYSIS_NODE_START:
        typeselection.analysisNodeStart();
        break;
    case textanalysis.ANALYSIS_LINK:
        typeselection.hide();
        break;
    }

    var backend_commit = false;
    ret.applyToGraph(rz_core.graph, backend_commit);

    if (finalize || sentence.length == 0) {
        typeselection.hide();
        $('span.ui-helper-hidden-accessible').hide();
    } else {
        $('span.ui-helper-hidden-accessible').show();
    }
}

function textSelect(inp, s, e) {
    e = e || s;
    if (inp.createTextRange) {
        var r = inp.createTextRange();
        r.collapse(true);
        r.moveEnd('character', e);
        r.moveStart('character', s);
        r.select();
    }else if(inp.setSelectionRange) {
        inp.focus();
        inp.setSelectionRange(s, e);
    }
}

function changeType(arg) {
    var lastnode = textanalysis.lastnode(),
        nodetype,
        id;

    if(!lastnode) {
        id = "new node";
    } else {
        id = lastnode.id;
    }
    nodetype = (arg === 'up'? textanalysis.selected_type_next() : textanalysis.selected_type_prev());

    if (arg === 'up') {
        rz_core.graph.editType(id, null, nodetype);
        typeselection.showChosenType(nodetype);
        rz_core.graph.findCoordinates(id, null);
    } else {
        rz_core.graph.editType(id, null, nodetype);
        typeselection.showChosenType(nodetype);
        rz_core.graph.findCoordinates(id, null);
    }
    rz_core.update_view__graph(true);
}

return {
    analyzeSentence: analyzeSentence,
    main:function () {
        if (element.length != 1) {
            return;
        }

        element.autocompleteTrigger({
            triggerStart: '#',
            triggerEnd: '',
            source: textanalysis.autocompleteCallback,
            response: function(element, ui) {
                ui.content.forEach(function (x) {
                    if (x.value.search(' ') != -1) {
                        x.value = '"' + x.value + '"';
                    }
                });
            },
            open: function() {
                $('.ui-autocomplete').css('width', '10px');
            },
        });

        $(document).keypress(function(e) {
            var ret = undefined;
            switch (e.keyCode) {
            case 9: //TAB
                e.preventDefault();
                changeType(e.shiftKey ? "up" : "down", textanalysis.lastnode());
                ret = false;
                break;
            case 37: //UP
                $('html, body').scrollLeft(0);
                break;
            case 39: //DOWN
                $('html, body').scrollLeft(0);
                break;
            case 38: //UP
                suggestionChange = true;
                break;
            case 40: //DOWN
                suggestionChange = true;
                break;
            }
            signal.signal(consts.KEYSTROKES, [{where: consts.KEYSTROKE_WHERE_DOCUMENT, keys: [e.keyCode]}]);
            return ret;
        });

        element.keypress(function(e) {
            var ret = undefined;
            switch (e.which) {
            case 13:
                if(!suggestionChange) {
                    text = element.val();
                    element.val("");
                    analyzeSentence(text, true);
                } else {
                    suggestionChange = false;
                }
                ret = false;
                break;
            case 37: //RIGHT
                $('body').scrollLeft(0);
                e.stopPropagation();
                ret = false;
                break;
            case 39: //LEFT
                $('body').scrollLeft(0);
                e.stopPropagation();
                ret = false;
                break;
            }
            signal.signal(consts.KEYSTROKES, [{where: consts.KEYSTROKE_WHERE_TEXTANALYSIS, keys:[e.which]}]);
            return ret;
        });

        if ('oninput' in document.documentElement) {
            element.on('input', function(e) {
                text = element.val();
                analyzeSentence(text, false);
            });
        } else {
            console.log('textanalysis.ui: fallback to polling');
            window.setInterval(function() {
                if (element.val() != text) {
                    if (text.length * 8 > 500) {
                        element.css('width', text.length * 8 + 20);
                    }
                    // text changed
                    text = element.val();
                    analyzeSentence(text, false);
                    suggestionChange = false;
                }
            }, 50);
        }
    }
};
}); // define
