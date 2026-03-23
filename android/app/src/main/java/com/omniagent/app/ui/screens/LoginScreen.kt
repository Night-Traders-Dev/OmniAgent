package com.omniagent.app.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.omniagent.app.ui.ChatUiState
import com.omniagent.app.ui.ChatViewModel
import com.omniagent.app.ui.theme.*

@Composable
fun LoginScreen(state: ChatUiState, vm: ChatViewModel) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var isRegister by remember { mutableStateOf(false) }
    var rememberDevice by remember { mutableStateOf(true) }

    Surface(modifier = Modifier.fillMaxSize(), color = BgDark) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(Icons.Filled.Lock, contentDescription = null, tint = Accent, modifier = Modifier.size(48.dp))
            Spacer(Modifier.height(12.dp))
            Text("OmniAgent", fontWeight = FontWeight.Bold, fontSize = 22.sp, color = TextPrimary)
            Text(if (isRegister) "Create Account" else "Sign In",
                fontSize = 13.sp, color = TextDim)
            Spacer(Modifier.height(24.dp))

            // Error
            state.authError?.let { err ->
                Surface(shape = RoundedCornerShape(6.dp), color = RedDark.copy(alpha = 0.15f),
                    modifier = Modifier.fillMaxWidth()) {
                    Text(err, modifier = Modifier.padding(10.dp), color = RedDark, fontSize = 13.sp)
                }
                Spacer(Modifier.height(8.dp))
            }

            OutlinedTextField(
                value = username, onValueChange = { username = it },
                modifier = Modifier.fillMaxWidth(), singleLine = true,
                placeholder = { Text("Username", color = TextDim) },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                    cursorColor = Accent, focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                    focusedContainerColor = CardDark, unfocusedContainerColor = CardDark,
                ),
                shape = RoundedCornerShape(8.dp),
            )
            Spacer(Modifier.height(8.dp))

            OutlinedTextField(
                value = password, onValueChange = { password = it },
                modifier = Modifier.fillMaxWidth(), singleLine = true,
                placeholder = { Text("Password", color = TextDim) },
                visualTransformation = PasswordVisualTransformation(),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                    cursorColor = Accent, focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                    focusedContainerColor = CardDark, unfocusedContainerColor = CardDark,
                ),
                shape = RoundedCornerShape(8.dp),
            )
            Spacer(Modifier.height(16.dp))

            // Remember device checkbox
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Checkbox(
                    checked = rememberDevice,
                    onCheckedChange = { rememberDevice = it },
                    colors = CheckboxDefaults.colors(
                        checkedColor = Accent, uncheckedColor = TextDim, checkmarkColor = Color.White,
                    ),
                )
                Text("Remember this device", fontSize = 13.sp, color = TextDim,
                    modifier = Modifier.padding(start = 4.dp))
            }
            Spacer(Modifier.height(8.dp))

            // Invite code (only for registration)
            var inviteCode by remember { mutableStateOf("") }
            if (isRegister) {
                OutlinedTextField(
                    value = inviteCode, onValueChange = { inviteCode = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Invite Code", color = TextDim) },
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                        cursorColor = Accent, focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                        focusedContainerColor = CardDark, unfocusedContainerColor = CardDark,
                    ),
                    shape = RoundedCornerShape(8.dp),
                )
                Spacer(Modifier.height(8.dp))
            }

            Button(
                onClick = {
                    if (username.isNotBlank() && password.isNotBlank()) {
                        vm.setRememberDevice(rememberDevice)
                        if (isRegister) vm.doRegister(username, password, inviteCode) else vm.doLogin(username, password)
                    }
                },
                modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Accent),
            ) {
                Text(if (isRegister) "Create Account" else "Sign In", fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(16.dp))

            TextButton(onClick = { isRegister = !isRegister }) {
                Text(
                    if (isRegister) "Already have an account? Sign In" else "Don't have an account? Register",
                    color = Accent, fontSize = 13.sp,
                )
            }
        }
    }
}
