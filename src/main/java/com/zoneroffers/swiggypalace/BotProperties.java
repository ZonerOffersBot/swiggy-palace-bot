package com.zoneroffers.swiggypalace;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;
@Component
@ConfigurationProperties(prefix="bot")
public class BotProperties {
 private String token="",adminIds="",databasePath="palace.db",webhookUrl=""; private long ownerId;
 public String getToken(){return token;} public void setToken(String v){token=v==null?"":v.trim();}
 public long getOwnerId(){return ownerId;} public void setOwnerId(long v){ownerId=v;}
 public String getAdminIds(){return adminIds;} public void setAdminIds(String v){adminIds=v==null?"":v;}
 public String getDatabasePath(){return databasePath;} public void setDatabasePath(String v){databasePath=v==null||v.isBlank()?"palace.db":v;}
 public String getWebhookUrl(){return webhookUrl;} public void setWebhookUrl(String v){webhookUrl=v==null?"":v.trim();}
}