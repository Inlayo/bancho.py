new Vue({
    el: "#app",
    delimiters: ["<%", "%>"],
    data() {
        return {
            data: {
                stats: {
                    out: [{}],
                    load: true
                },
                grades: {},
                scores: {
                    recent: {
                        out: [],
                        load: true,
                        more: {
                            limit: 5,
                            full: true,
                            total: 0
                        }
                    },
                    best: {
                        out: [],
                        load: true,
                        more: {
                            limit: 5,
                            full: true,
                            total: 0
                        }
                    },
                    first: {
                        out: [],
                        load: true,
                        more: {
                            limit: 5,
                            full: true,
                            total: 0
                        }
                    }
                },
                maps: {
                    most: {
                        out: [],
                        load: true,
                        more: {
                            limit: 5,
                            full: true,
                            total: 0
                        }
                    }
                },
                status: {}
            },
            mode: mode,
            mods: mods,
            modegulag: 0,
            userid: userid
        };
    },
    created() {
        // starting a page
        this.applyQueryParams();
        this.modegulag = this.StrtoGulagInt();
        this.LoadProfileData();
        this.LoadAllofdata();
        this.LoadUserStatus();
    },
    methods: {
        applyQueryParams() {
            try {
                const params = new URLSearchParams(window.location.search);
                const modeParam = params.get('mode');
                const rxParam = params.get('rx');

                // Map query to strings: mode 0-3 => std/taiko/catch/mania; rx 0-2 => vn/rx/ap
                const modeMap = { '0': 'std', '1': 'taiko', '2': 'catch', '3': 'mania' };
                const rxMap = { '0': 'vn', '1': 'rx', '2': 'ap' };

                let nextMode = this.mode;
                let nextMods = this.mods;

                if (modeParam !== null && modeMap.hasOwnProperty(modeParam)) {
                    nextMode = modeMap[modeParam];
                }
                if (rxParam !== null && rxMap.hasOwnProperty(rxParam)) {
                    nextMods = rxMap[rxParam];
                }

                // Enforce validity based on constraints
                // mode std(0): vn/rx/ap, taiko(1): vn/rx, catch(2): vn/rx, mania(3): vn only
                if (nextMode === 'mania' && nextMods !== 'vn') {
                    nextMods = 'vn';
                } else if ((nextMode === 'taiko' || nextMode === 'catch') && nextMods === 'ap') {
                    nextMods = 'vn';
                }

                this.mode = nextMode;
                this.mods = nextMods;

                // Sync URL query to canonical form
                this.syncUrlQuery();
            } catch (e) {
                // If URLSearchParams not available or any error, ignore
            }
        },
        syncUrlQuery() {
            try {
                const modeToInt = { 'std': 0, 'taiko': 1, 'catch': 2, 'mania': 3 };
                const modsToInt = { 'vn': 0, 'rx': 1, 'ap': 2 };
                const m = modeToInt[this.mode];
                let r = modsToInt[this.mods];

                // Clamp per constraints
                if (this.mode === 'mania') {
                    r = 0; // vn only
                } else if (this.mode === 'taiko' || this.mode === 'catch') {
                    if (r === 2) r = 0; // no AP, fallback to VN
                }

                const params = new URLSearchParams(window.location.search);
                params.set('mode', String(m));
                params.set('rx', String(r));
                const newUrl = `/u/${this.userid}?${params.toString()}`;
                history.replaceState(null, '', newUrl);
            } catch (e) {
                // noop
            }
        },
        LoadAllofdata() {
            this.LoadMostBeatmaps();
            this.LoadScores('best');
            this.LoadScores('recent');
            this.LoadScores('first');
        },
        LoadProfileData() {
            this.$set(this.data.stats, 'load', true);
            this.$axios.get(`${window.location.protocol}//api.${domain}/v1/get_player_info`, {
                params: {
                    id: this.userid,
                    scope: 'all'
                }
            })
                .then(res => {
                    this.$set(this.data.stats, 'out', res.data.player.stats);
                    this.data.stats.load = false;
                });
        },
        LoadScores(sort) {
            this.$set(this.data.scores[`${sort}`], 'load', true);
            this.$axios.get(`${window.location.protocol}//api.${domain}/v1/get_player_scores`, {
                params: {
                    id: this.userid,
                    mode: this.StrtoGulagInt(),
                    scope: sort,
                    limit: 100 //API MAX = 100
                }
            })
                .then(res => {
                    const allScores = res.data.scores; // fetch all scores
                    this.data.scores[`${sort}`].out = allScores.slice(0, this.data.scores[`${sort}`].more.limit); // save only up to limit
                    //this.data.scores[`${sort}`].out = res.data.scores;
                    this.data.scores[`${sort}`].load = false
                    this.data.scores[`${sort}`].more.full = this.data.scores[`${sort}`].out.length != this.data.scores[`${sort}`].more.limit;
                    this.data.scores[`${sort}`].more.total = allScores.length //total
                });
        },
        LoadMostBeatmaps() {
            this.$set(this.data.maps.most, 'load', true);
            this.$axios.get(`${window.location.protocol}//api.${domain}/v1/get_player_most_played`, {
                params: {
                    id: this.userid,
                    mode: this.StrtoGulagInt(),
                    limit: 100 //API MAX = 100
                }
            })
                .then(res => {
                    const allScores = res.data.maps; // fetch all scores
                    this.data.maps.most.out = allScores.slice(0, this.data.maps.most.more.limit); // save only up to limit
                    //this.data.maps.most.out = res.data.maps;
                    this.data.maps.most.load = false;
                    this.data.maps.most.more.full = this.data.maps.most.out.length != this.data.maps.most.more.limit;
                    this.data.maps.most.more.total = allScores.length //total
                });
        },
        LoadUserStatus() {
            this.$axios.get(`${window.location.protocol}//api.${domain}/v1/get_player_status`, {
                params: {
                    id: this.userid
                }
            })
                .then(res => {
                    this.$set(this.data, 'status', res.data.player_status)
                })
                .catch(function (error) {
                    clearTimeout(loop);
                    console.log(error);
                });
            loop = setTimeout(this.LoadUserStatus, 5000);
        },
        ChangeModeMods(mode, mods) {
            if (window.event)
                window.event.preventDefault();

            this.mode = mode;
            this.mods = mods;

            this.modegulag = this.StrtoGulagInt();
            this.data.scores.recent.more.limit = 5
            this.data.scores.best.more.limit = 5
            this.data.maps.most.more.limit = 5
            this.syncUrlQuery();
            this.LoadAllofdata();
        },
        AddLimit(which) {
            if (window.event)
                window.event.preventDefault();

            if (which == 'bestscore') {
                this.data.scores.best.more.limit += 10;
                this.LoadScores('best');
            } else if (which == 'recentscore') {
                this.data.scores.recent.more.limit += 10;
                this.LoadScores('recent');
            } else if (which == 'firstscore') {
                this.data.scores.first.more.limit += 10;
                this.LoadScores('first');
            } else if (which == 'mostplay') {
                this.data.maps.most.more.limit += 10;
                this.LoadMostBeatmaps();
            }
        },
        actionIntToStr(d) {
            switch (d.action) {
                case 0:
                    return 'Idle: 🔍 Song Select';
                case 1:
                    return '🌙 AFK';
                case 2:
                    return `Playing: 🎶 ${d.info_text}`;
                case 3:
                    return `Editing: 🔨 ${d.info_text}`;
                case 4:
                    return `Modding: 🔨 ${d.info_text}`;
                case 5:
                    return 'In Multiplayer: Song Select';
                case 6:
                    return `Watching: 👓 ${d.info_text}`;
                // 7 not used
                case 8:
                    return `Testing: 🎾 ${d.info_text}`;
                case 9:
                    return `Submitting: 🧼 ${d.info_text}`;
                // 10 paused, never used
                case 11:
                    return 'Idle: 🏢 In multiplayer lobby';
                case 12:
                    return `In Multiplayer: Playing 🌍 ${d.info_text} 🎶`;
                case 13:
                    return 'Idle: 🔍 Searching for beatmaps in osu!direct';
                default:
                    return 'Unknown: 🚔 not yet implemented!';
            }
        },
        addCommas(nStr) {
            nStr += '';
            var x = nStr.split('.');
            var x1 = x[0];
            var x2 = x.length > 1 ? '.' + x[1] : '';
            var rgx = /(\d+)(\d{3})/;
            while (rgx.test(x1)) {
                x1 = x1.replace(rgx, '$1' + ',' + '$2');
            }
            return x1 + x2;
        },
        secondsToDhm(seconds) {
            seconds = Number(seconds);
            var dDisplay = `${Math.floor(seconds / (3600 * 24))}d `;
            var hDisplay = `${Math.floor(seconds % (3600 * 24) / 3600)}h `;
            var mDisplay = `${Math.floor(seconds % 3600 / 60)}m `;
            return dDisplay + hDisplay + mDisplay;
        },
        StrtoGulagInt() {
            switch (this.mode + "|" + this.mods) {
                case 'std|vn':
                    return 0;
                case 'taiko|vn':
                    return 1;
                case 'catch|vn':
                    return 2;
                case 'mania|vn':
                    return 3;
                case 'std|rx':
                    return 4;
                case 'taiko|rx':
                    return 5;
                case 'catch|rx':
                    return 6;
                case 'std|ap':
                    return 8;
                default:
                    return -1;
            }
        },
        StrtoModeInt() {
            switch (this.mode) {
                case 'std':
                    return 0;
                case 'taiko':
                    return 1;
                case 'catch':
                    return 2;
                case 'mania':
                    return 3;
            }
        },
    },
    computed: {}
});
