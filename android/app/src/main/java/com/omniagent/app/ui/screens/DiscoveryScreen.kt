package com.omniagent.app.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.omniagent.app.ui.ChatUiState
import com.omniagent.app.ui.ChatViewModel
import com.omniagent.app.ui.theme.*

@Composable
fun DiscoveryScreen(state: ChatUiState, vm: ChatViewModel) {
    var manualAddress by remember { mutableStateOf("") }
    var pairingCode by remember { mutableStateOf("") }
    var connectMode by remember { mutableStateOf("main") } // main, manual, pairing

    Surface(modifier = Modifier.fillMaxSize(), color = BgDark) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(Icons.Filled.Wifi, contentDescription = null, tint = Accent,
                modifier = Modifier.size(64.dp))
            Spacer(Modifier.height(16.dp))
            Text("OmniAgent", fontWeight = FontWeight.Bold, fontSize = 24.sp, color = TextPrimary)
            Text("Connect to your server", fontSize = 14.sp, color = TextDim)
            Spacer(Modifier.height(32.dp))

            when (state.connectionState) {
                "scanning" -> {
                    LinearProgressIndicator(
                        progress = { state.scanProgress },
                        modifier = Modifier.fillMaxWidth(),
                        color = Accent, trackColor = BorderDark,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text("Scanning network... ${(state.scanProgress * 100).toInt()}%",
                        fontSize = 12.sp, color = TextDim)
                    state.discoveredServers.forEach { server ->
                        Spacer(Modifier.height(8.dp))
                        Surface(
                            onClick = { vm.connectToServer(server.ip, server.port) },
                            shape = RoundedCornerShape(8.dp), color = CardDark,
                            border = BorderStroke(1.dp, GreenDark),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Row(modifier = Modifier.padding(16.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically) {
                                Column {
                                    Text(server.ip, fontWeight = FontWeight.Bold, color = TextPrimary)
                                    Text("v${server.version} - ${server.agents.size} agents",
                                        fontSize = 12.sp, color = TextDim)
                                }
                                Text("Connect", color = GreenDark, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
                else -> {
                    when (connectMode) {
                        "main" -> {
                            // Auto scan
                            Button(
                                onClick = { vm.scanForServer() },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Accent),
                            ) {
                                Icon(Icons.Filled.Search, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(8.dp))
                                Text("Auto-Discover (LAN)", fontWeight = FontWeight.Bold)
                            }
                            Spacer(Modifier.height(12.dp))

                            // Pairing code (remote — the main new feature)
                            Button(
                                onClick = { connectMode = "pairing" },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = GreenDark),
                            ) {
                                Icon(Icons.Filled.Cloud, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(8.dp))
                                Text("Connect with Pairing Code", fontWeight = FontWeight.Bold)
                            }
                            Spacer(Modifier.height(12.dp))

                            // Manual
                            OutlinedButton(
                                onClick = { connectMode = "manual" },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                border = BorderStroke(1.dp, BorderDark),
                            ) {
                                Text("Enter Address Manually", color = TextDim)
                            }
                        }

                        "pairing" -> {
                            // Pairing code entry
                            Text("Enter Pairing Code", fontWeight = FontWeight.Bold, fontSize = 16.sp, color = TextPrimary)
                            Spacer(Modifier.height(4.dp))
                            Text("Find this on the server console when it starts.",
                                fontSize = 12.sp, color = TextDim, textAlign = TextAlign.Center)
                            Spacer(Modifier.height(16.dp))

                            OutlinedTextField(
                                value = pairingCode,
                                onValueChange = { pairingCode = it.trim().lowercase() },
                                modifier = Modifier.fillMaxWidth(),
                                placeholder = { Text("e.g. a3f2b1", color = TextDim) },
                                singleLine = true,
                                textStyle = androidx.compose.ui.text.TextStyle(
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 20.sp,
                                    textAlign = TextAlign.Center,
                                    color = TextPrimary,
                                ),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = GreenDark, unfocusedBorderColor = BorderDark,
                                    cursorColor = GreenDark,
                                    focusedContainerColor = CardDark, unfocusedContainerColor = CardDark,
                                ),
                                shape = RoundedCornerShape(8.dp),
                            )
                            Spacer(Modifier.height(12.dp))

                            Button(
                                onClick = { if (pairingCode.isNotBlank()) vm.connectWithPairingCode(pairingCode) },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = GreenDark),
                                enabled = pairingCode.length >= 4,
                            ) {
                                Icon(Icons.Filled.Cloud, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(8.dp))
                                Text("Connect", fontWeight = FontWeight.Bold)
                            }
                            Spacer(Modifier.height(12.dp))
                            TextButton(onClick = { connectMode = "main" }) {
                                Text("Back", color = TextDim)
                            }
                        }

                        "manual" -> {
                            OutlinedTextField(
                                value = manualAddress,
                                onValueChange = { manualAddress = it },
                                modifier = Modifier.fillMaxWidth(),
                                placeholder = { Text("192.168.1.100:8000", color = TextDim) },
                                singleLine = true,
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = Accent, unfocusedBorderColor = BorderDark,
                                    cursorColor = Accent, focusedTextColor = TextPrimary, unfocusedTextColor = TextPrimary,
                                    focusedContainerColor = CardDark, unfocusedContainerColor = CardDark,
                                ),
                                shape = RoundedCornerShape(8.dp),
                            )
                            Spacer(Modifier.height(8.dp))
                            OutlinedButton(
                                onClick = { if (manualAddress.isNotBlank()) vm.connectManual(manualAddress) },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                border = BorderStroke(1.dp, Accent),
                            ) {
                                Text("Connect", color = Accent)
                            }
                            Spacer(Modifier.height(12.dp))
                            TextButton(onClick = { connectMode = "main" }) {
                                Text("Back", color = TextDim)
                            }
                        }
                    }

                    // Error
                    state.error?.let { error ->
                        Spacer(Modifier.height(16.dp))
                        Text(error, fontSize = 12.sp, color = RedDark, textAlign = TextAlign.Center)
                    }
                }
            }
        }
    }
}
