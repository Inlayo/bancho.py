new Vue({
  el: "#dashboard",
  delimiters: ["<%", "%>"],
  data() {
    return {
      online_users: 0,
      user_list: "",
    };
  },
  created() {
    var vm = this;
    vm.GetOnlineUsers();
    vm.LoadOnlineUsers();
  },
  methods: {
    GetOnlineUsers() {
      var vm = this;
      vm.$axios
        .get(`${window.location.protocol}//api.${domain}/v1/get_player_count`)
        .then(function (response) {
          vm.online_users = response.data.counts.online;
        });
    },
    LoadOnlineUsers() {
      var vm = this;
      vm.$axios
        .get(`https://c.${domain}/online`, { responseType: "text" })
        .then(function (response) {
          const data = response.data;
          const userSection = data.split("users:")[1]?.split("bots:")[0];
          const botSection = data.split("bots:")[1];
          let users = [];
          let bots = [];
          if (userSection) {
            users = userSection
              .trim()
              .split("\n")
              .map((line) => {
                const parts = line.trim().split(":");
                if (parts.length === 2) {
                  return `${parts[1]}${parts[0].replace(/\s+/g, "")}`;
                }
              })
              .filter((user) => user);
          }
          if (botSection) {
            bots = botSection
              .trim()
              .split("\n")
              .map((line) => {
                const parts = line.trim().split(":");
                if (parts.length === 2) {
                  return `${parts[1]}${parts[0].replace(/\s+/g, "")}`;
                }
              })
              .filter((bot) => bot);
          }
          vm.user_list = [...bots, ...users].join(", ");
        })
        .catch(function (error) {
          console.error("Error fetching user list:", error);
        });
    },
    addCommas(nStr) {
      nStr += "";
      var x = nStr.split(".");
      var x1 = x[0];
      var x2 = x.length > 1 ? "." + x[1] : "";
      var rgx = /(\d+)(\d{3})/;
      while (rgx.test(x1)) {
        x1 = x1.replace(rgx, "$1" + "," + "$2");
      }
      return x1 + x2;
    },
  },
  computed: {},
});
