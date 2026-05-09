/**
 * One alert statement with detailed conditions
 * @param {[string, string]} data Data received from server
 * @param {Object} submitBtn submitBtn properties
 * @param {Object} sendBtn sendBtn properties
 * @param {Object} OEV OEV properties
 * @param {Object} NEV NEV properties
 */
function detail(data, submitBtn, sendBtn, OEV, NEV) {
  if (data[1] === null && data[0] === "sent") { // First attempt to change nickname
    submitBtn.disabled = false
    alert("Verification email sent successfully!")
  } else if (data[1] === null && !isNaN(data[0])) { // Multiple attempts to change nickname
    submitBtn.disabled = false
    alert(`Verification email has been sent. You can try again in ${data} seconds.`)
  } else if (data[1] === null && data[0].startsWith("ERROR | ")) { // Email error detected
    sendBtn.disabled = false; OEV.style.display = "none"; NEV.style.display = "none"
    alert(`ERROR! report admin plz \n\n${data[0]}`)
  }
  else if (data[0] === "sent" && data[1] === "sent") { // First attempt to change email
    submitBtn.disabled = false
    alert("Verification old & new email sent successfully!\nCheck both emails");
  } else if (!isNaN(data[0]) && !isNaN(data[1])) { // Multiple attempts to change email
    submitBtn.disabled = false
    alert(`Verification old & new email has been sent. You can try again in old:${data[0]}, new:${data[1]} seconds.`)
  } else if (!isNaN(data[0]) && data[1] === "sent") { // Old email already sent, new email just sent
    submitBtn.disabled = false
    alert(`Verification old email has been sent. You can try again in ${data[0]} seconds. \n\nVerification new email sent successfully!`)
  } else if (data[0] === "sent" && !isNaN(data[1])) { // Old email just sent, new email already sent (practically impossible)
    submitBtn.disabled = false
    alert(`Impossible\nVerification old email sent successfully! \n\nVerification new email has been sent. You can try again in ${data[1]} seconds.`)
  }
  else if (data[0] === "sent" && data[1].startsWith("ERROR | ")) { // Old email just sent + new email error detected
    sendBtn.disabled = false; NEV.style.display = "none"
    alert(`Verification old email sent successfully! \n\nERROR! (new) report admin plz \n\n${data[1]}`);
  } else if (!isNaN(data[0]) && data[1].startsWith("ERROR | ")) { // Old email already sent + new email error detected
    sendBtn.disabled = false; NEV.style.display = "none"
    alert(`Verification old email has been sent. You can try again in ${data[0]} seconds. \n\nERROR! (new) report admin plz \n\n${data[1]}`);
  } else if (data[1] === "sent" && data[0].startsWith("ERROR | ")) { // Old email error detected + new email just sent
    sendBtn.disabled = false; OEV.style.display = "none"
    alert(`Verification new email sent successfully! \n\nERROR! (old) report admin plz \n\n${data[0]}`);
  } else if (!isNaN(data[1]) && data[0].startsWith("ERROR | ")) { // Old email error detected + new email already sent
    sendBtn.disabled = false; OEV.style.display = "none"
    alert(`Verification new email has been sent. You can try again in ${data[1]} seconds. \n\nERROR! (old) report admin plz \n\n${data[0]}`);
  } else if (data[0].startsWith("ERROR | ") && data[1].startsWith("ERROR | ")) { // Both emails error detected
    sendBtn.disabled = false; OEV.style.display = "none"; NEV.style.display = "none"
    alert(`ERROR! (both) report admin plz \n\n${data[0]}\n\n${data[1]}`);
  }
}

/**
 * Two alert statements with simpler conditions
 * @param {[string, string]} data Data received from server
 * @param {Object} submitBtn submitBtn properties
 * @param {Object} sendBtn sendBtn properties
 * @param {Object} OEV OEV properties
 * @param {Object} NEV NEV properties
 */
function simple(data, submitBtn, sendBtn, OEV, NEV) {
  if (data[0] === "sent") {
    submitBtn.disabled = false
    alert("Verification old email sent successfully!")
  } else if (!isNaN(data[0])) {
    submitBtn.disabled = false
    alert(`Verification old email has been sent. You can try again in ${data[0]} seconds.`)
  } else if (data[0].startsWith("ERROR | ")) {
    sendBtn.disabled = false; OEV.style.display = "none"
    alert(`ERROR! (old) report admin plz \n${data[0]}`)
  }
  if (!data[1]);
  else if (data[1] === "sent") {
    submitBtn.disabled = false
    alert("Verification new email sent successfully!")
  } else if (!isNaN(data[1])) {
    submitBtn.disabled = false
    alert(`Verification new email has been sent. You can try again in ${data[1]} seconds.`)
  } else if (data[1].startsWith("ERROR | ")) {
    sendBtn.disabled = false; NEV.style.display = "none"
    alert(`ERROR! (new) report admin plz \n${data[1]}`)
  }
}